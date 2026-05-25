from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Callable
from uuid import uuid5, NAMESPACE_URL

from wx_ai_assistant.application.context_builder import ContextBuilder
from wx_ai_assistant.application.ai_turn import AiTurnParser
from wx_ai_assistant.application.message_ingestion import MessageIngestionService
from wx_ai_assistant.application.send_queue import SendQueue
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus, SendTaskStatus
from wx_ai_assistant.domain.models import ConversationIdentity, ListenTarget, Message
from wx_ai_assistant.ports.ai_gateway import AiGateway
from wx_ai_assistant.ports.repository import Repository
from wx_ai_assistant.ports.wechat_driver import WechatDriver
from wx_ai_assistant.infrastructure.observability.console import print_error_block


@dataclass
class PendingAiTurn:
    identity: ConversationIdentity
    trigger_message: Message
    last_other_message_at: float


class WechatApplicationService:
    def __init__(
        self,
        repo: Repository,
        driver: WechatDriver,
        ingestion: MessageIngestionService,
        context_builder: ContextBuilder,
        ai: AiGateway,
        send_queue: SendQueue,
        ai_turn_parser: AiTurnParser | None = None,
        ai_turn_quiet_seconds: float = 0.0,
        ai_duplicate_guard_seconds: float = 120.0,
        diagnostics_context_chars: int = 1200,
        driver_lock=None,
    ):
        self.repo = repo
        self.driver = driver
        self.ingestion = ingestion
        self.context_builder = context_builder
        self.ai = ai
        self.send_queue = send_queue
        self.ai_turn_parser = ai_turn_parser or AiTurnParser(strict_json=False)
        self.ai_turn_quiet_seconds = max(0.0, ai_turn_quiet_seconds)
        self.ai_duplicate_guard_seconds = max(0.0, ai_duplicate_guard_seconds)
        self.diagnostics_context_chars = max(0, diagnostics_context_chars)
        self.driver_lock = driver_lock
        self._pending_ai_turns: dict[str, PendingAiTurn] = {}
        self._recent_trigger_keys: dict[str, float] = {}
        self._last_visible_snapshots: list[dict] = []
        self._last_ai_turns: list[dict] = []
        self._last_ai_errors: list[dict] = []
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

    def delete_listen_target(self, conversation_id: str) -> bool:
        self.repo.set_listen_status(conversation_id, ListenStatus.STOPPED, "deleted")
        self._pending_ai_turns.pop(conversation_id, None)
        return self.repo.delete_listen_target(conversation_id)

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

    def clear_conversation_memory(self, conversation_id: str) -> dict[str, int]:
        self._pending_ai_turns.pop(conversation_id, None)
        return self.repo.clear_conversation_memory(conversation_id)

    def list_ai_decision_logs(
        self,
        conversation_id: str | None = None,
        run_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        return self.repo.list_ai_decision_logs(conversation_id=conversation_id, run_id=run_id, limit=limit)

    def poll_listeners_once(self) -> None:
        if self._poll_once is None:
            raise RuntimeError("监听调度器尚未绑定")
        self._poll_once()

    def current_conversation(self) -> ConversationIdentity | None:
        with self._driver_guard():
            return self.driver.get_current_conversation()

    def diagnostics_snapshot(self) -> dict:
        targets = self.repo.list_listen_targets()
        tasks = self.repo.list_send_tasks(limit=20)
        pending = [task for task in tasks if task.status == SendTaskStatus.PENDING]
        failed = [task for task in tasks if task.status == SendTaskStatus.FAILED]
        recent_by_target = {
            target.conversation.conversation_id: [
                asdict(message) for message in self.repo.list_recent_messages(target.conversation.conversation_id, limit=10)
            ]
            for target in targets
        }
        try:
            with self._driver_guard():
                driver_status = self.driver.status().__dict__
        except Exception as exc:
            driver_status = {"ok": False, "message": str(exc)}
        try:
            with self._driver_guard():
                current = self.driver.get_current_conversation()
        except Exception:
            current = None

        return {
            "driver_status": driver_status,
            "current_conversation": asdict(current) if current else None,
            "listen_targets": [asdict(target) for target in targets],
            "send_task_counts": {
                "recent_total": len(tasks),
                "pending": len(pending),
                "failed": len(failed),
            },
            "recent_send_tasks": [asdict(task) for task in tasks],
            "recent_messages_by_target": recent_by_target,
            "pending_ai_turns": [
                {
                    "conversation_id": pending.identity.conversation_id,
                    "display_name": pending.identity.display_name,
                    "trigger_message_id": pending.trigger_message.message_id,
                    "trigger_content": pending.trigger_message.content,
                    "age_seconds": round(time.monotonic() - pending.last_other_message_at, 3),
                }
                for pending in self._pending_ai_turns.values()
            ],
            "last_visible_snapshots": self._last_visible_snapshots[-10:],
            "last_ai_turns": self._last_ai_turns[-10:],
            "last_ai_errors": self._last_ai_errors[-10:],
        }

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
        self._record_visible_snapshot(identity, messages)
        triggers = self.ingestion.ingest_realtime_messages(identity, messages)
        triggers = self._filter_recent_duplicate_triggers(identity, triggers)
        if not triggers:
            return
        msg = triggers[-1]
        self._pending_ai_turns[identity.conversation_id] = PendingAiTurn(
            identity=identity,
            trigger_message=msg,
            last_other_message_at=time.monotonic(),
        )

    def flush_ready_ai_turns(self, force: bool = False) -> None:
        now = time.monotonic()
        ready_ids = [
            conversation_id
            for conversation_id, pending in self._pending_ai_turns.items()
            if force or now - pending.last_other_message_at >= self.ai_turn_quiet_seconds
        ]
        for conversation_id in ready_ids:
            pending = self._pending_ai_turns.pop(conversation_id, None)
            if pending is None:
                continue
            self._generate_ai_turn(pending)

    def _generate_ai_turn(self, pending: PendingAiTurn) -> None:
        try:
            context = self.context_builder.build_context(pending.identity, pending.trigger_message)
            identity_setter = getattr(self.ai, "set_contact_identity", None)
            if callable(identity_setter):
                identity_setter(pending.identity)
            raw_reply = self.ai.generate_reply(context=context, trigger_message=pending.trigger_message).strip()
            turn = self.ai_turn_parser.parse(raw_reply)
            self._record_ai_turn(pending, context, raw_reply, turn.messages, turn.done)
            if not turn.done:
                self._record_ai_error(pending.identity, "AI 未按本轮完成协议输出 done=true，已跳过本轮。")
                return
            for reply in turn.messages:
                self.send_queue.enqueue(
                    pending.identity.conversation_id,
                    reply,
                    trigger_message_id=pending.trigger_message.message_id,
                )
        except Exception as exc:
            self._record_ai_error(pending.identity, str(exc))

    def _filter_recent_duplicate_triggers(self, identity: ConversationIdentity, triggers: list[Message]) -> list[Message]:
        if not triggers or self.ai_duplicate_guard_seconds <= 0:
            return triggers
        now = time.monotonic()
        cutoff = now - self.ai_duplicate_guard_seconds
        self._recent_trigger_keys = {
            key: seen_at for key, seen_at in self._recent_trigger_keys.items() if seen_at >= cutoff
        }

        fresh: list[Message] = []
        for msg in triggers:
            key = self._trigger_key(identity, msg)
            seen_at = self._recent_trigger_keys.get(key)
            if seen_at is not None and now - seen_at <= self.ai_duplicate_guard_seconds:
                continue
            self._recent_trigger_keys[key] = now
            fresh.append(msg)
        return fresh

    def _trigger_key(self, identity: ConversationIdentity, msg: Message) -> str:
        normalized = " ".join(msg.content.split())
        sender = msg.sender_name or msg.sender_type.value
        return f"{identity.conversation_id}|{sender}|{normalized}"

    def _record_visible_snapshot(self, identity: ConversationIdentity, messages: list[Message]) -> None:
        self._last_visible_snapshots.append(
            {
                "conversation_id": identity.conversation_id,
                "display_name": identity.display_name,
                "at_monotonic": round(time.monotonic(), 3),
                "count": len(messages),
                "messages": [
                    {
                        "sender_type": msg.sender_type.value,
                        "message_type": msg.message_type.value,
                        "content": msg.content,
                        "fingerprint": msg.fingerprint,
                    }
                    for msg in messages[-20:]
                ],
            }
        )
        self._last_visible_snapshots = self._last_visible_snapshots[-20:]

    def _record_ai_turn(
        self,
        pending: PendingAiTurn,
        context: str,
        raw_reply: str,
        parsed_messages: list[str],
        done: bool,
    ) -> None:
        context_preview = context[-self.diagnostics_context_chars :] if self.diagnostics_context_chars else ""
        decision = getattr(self.ai, "last_decision_snapshot", None)
        entry = {
            "conversation_id": pending.identity.conversation_id,
            "display_name": pending.identity.display_name,
            "trigger_message_id": pending.trigger_message.message_id,
            "trigger_content": pending.trigger_message.content,
            "done": done,
            "parsed_messages": parsed_messages,
            "raw_reply": raw_reply,
            "context_tail": context_preview,
            "at_monotonic": round(time.monotonic(), 3),
        }
        if isinstance(decision, dict):
            entry.update(decision)
            entry["trigger_content"] = pending.trigger_message.content
        self._last_ai_turns.append(entry)
        self._last_ai_turns = self._last_ai_turns[-20:]

    def _record_ai_error(self, identity: ConversationIdentity, error: str) -> None:
        self._last_ai_errors.append(
            {
                "conversation_id": identity.conversation_id,
                "display_name": identity.display_name,
                "error": error,
                "at_monotonic": round(time.monotonic(), 3),
            }
        )
        self._last_ai_errors = self._last_ai_errors[-20:]
        print_error_block("AI ERROR", error, {"target": identity.display_name})

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

    def _driver_guard(self):
        if self.driver_lock is None:
            from contextlib import nullcontext

            return nullcontext()
        return self.driver_lock
