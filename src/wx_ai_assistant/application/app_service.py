from __future__ import annotations

from typing import Callable
from uuid import uuid5, NAMESPACE_URL

from wx_ai_assistant.application.context_builder import ContextBuilder
from wx_ai_assistant.application.message_ingestion import MessageIngestionService
from wx_ai_assistant.application.send_queue import SendQueue
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus, SendTaskStatus
from wx_ai_assistant.domain.models import ConversationIdentity, ListenTarget, Message
from wx_ai_assistant.ports.ai_gateway import AiGateway
from wx_ai_assistant.ports.repository import Repository
from wx_ai_assistant.ports.wechat_driver import WechatDriver


class WechatApplicationService:
    def __init__(
        self,
        repo: Repository,
        driver: WechatDriver,
        ingestion: MessageIngestionService,
        context_builder: ContextBuilder,
        ai: AiGateway,
        send_queue: SendQueue,
    ):
        self.repo = repo
        self.driver = driver
        self.ingestion = ingestion
        self.context_builder = context_builder
        self.ai = ai
        self.send_queue = send_queue
        self._start_listener: Callable[[str], None] | None = None
        self._stop_listener: Callable[[str, str | None], None] | None = None
        self._poll_once: Callable[[], None] | None = None

    def initialize(self):
        return self.driver.initialize()

    def status(self):
        return self.driver.status()

    def add_listen_target(
        self,
        display_name: str,
        conversation_type: ConversationType,
        remark_name: str | None = None,
        local_id: str | None = None,
    ) -> ListenTarget:
        self._ensure_friend_conversation(conversation_type)
        conversation_id = self._conversation_id(conversation_type, display_name, remark_name, local_id)
        identity = ConversationIdentity(
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            display_name=display_name,
            remark_name=remark_name,
            local_id=local_id,
        )
        target = ListenTarget(conversation=identity, status=ListenStatus.STOPPED)
        self.repo.upsert_listen_target(target)
        return target

    def list_listen_targets(self) -> list[ListenTarget]:
        return self.repo.list_listen_targets()

    def bind_listener_controls(
        self,
        start_listener: Callable[[str], None],
        stop_listener: Callable[[str, str | None], None],
        poll_once: Callable[[], None] | None = None,
    ) -> None:
        self._start_listener = start_listener
        self._stop_listener = stop_listener
        self._poll_once = poll_once

    def start_listen_target(self, conversation_id: str) -> None:
        if self._start_listener is None:
            raise RuntimeError("监听调度器尚未绑定")
        self._start_listener(conversation_id)

    def stop_listen_target(self, conversation_id: str, reason: str | None = None) -> None:
        if self._stop_listener is None:
            raise RuntimeError("监听调度器尚未绑定")
        self._stop_listener(conversation_id, reason)

    def list_recent_messages(self, conversation_id: str, limit: int = 50):
        return self.repo.list_recent_messages(conversation_id, limit)

    def send_text_manually(self, conversation_id: str, content: str):
        identity = self.repo.get_conversation(conversation_id)
        if identity is None:
            raise ValueError(f"会话不存在: {conversation_id}")
        self._ensure_friend_conversation(identity.conversation_type)
        if not content.strip():
            raise ValueError("发送内容不能为空")
        return self.send_queue.enqueue(conversation_id=conversation_id, content=content)

    def list_send_tasks(
        self,
        conversation_id: str | None = None,
        status: SendTaskStatus | None = None,
        limit: int = 50,
    ):
        return self.repo.list_send_tasks(conversation_id=conversation_id, status=status, limit=limit)

    def get_send_task(self, send_task_id: str):
        return self.repo.get_send_task(send_task_id)

    def poll_listeners_once(self) -> None:
        if self._poll_once is None:
            raise RuntimeError("监听调度器尚未绑定")
        self._poll_once()

    def current_conversation(self) -> ConversationIdentity | None:
        return self.driver.get_current_conversation()

    def create_mock_text_message(self, conversation_id: str, content: str, sender_name: str = "other") -> Message:
        identity = self.repo.get_conversation(conversation_id)
        if identity is None:
            raise ValueError(f"会话不存在: {conversation_id}")

        status = self.driver.switch_conversation(identity)
        if not status.ok:
            raise RuntimeError(status.message)

        if not hasattr(self.driver, "inject_other_text"):
            raise RuntimeError("当前 Driver 不支持 mock 消息注入。请在 APP_DRIVER_MODE=mock 下使用。")
        msg = self.driver.inject_other_text(identity, content, sender_name)  # type: ignore[attr-defined]
        self.handle_realtime_messages(identity, [msg])
        return msg

    def handle_realtime_messages(self, identity: ConversationIdentity, messages: list[Message]) -> None:
        if self.repo.get_listen_target(identity.conversation_id) is None:
            return
        triggers = self.ingestion.ingest_realtime_messages(identity, messages)
        for msg in triggers:
            context = self.context_builder.build_context(identity, msg)
            reply = self.ai.generate_reply(context=context, trigger_message=msg).strip()
            if reply:
                self.send_queue.enqueue(identity.conversation_id, reply, trigger_message_id=msg.message_id)

    def handle_baseline_messages(self, identity: ConversationIdentity, messages: list[Message]) -> None:
        if self.repo.get_listen_target(identity.conversation_id) is None:
            return
        self.ingestion.ingest_baseline_messages(identity, messages)

    def _conversation_id(self, conversation_type: ConversationType, display_name: str, remark_name: str | None, local_id: str | None) -> str:
        stable = f"{conversation_type.value}|{local_id or ''}|{remark_name or ''}|{display_name}"
        return "conv_" + uuid5(NAMESPACE_URL, stable).hex

    def _ensure_friend_conversation(self, conversation_type: ConversationType) -> None:
        if conversation_type != ConversationType.FRIEND:
            raise ValueError("第一阶段只支持好友私聊，不支持群聊")
