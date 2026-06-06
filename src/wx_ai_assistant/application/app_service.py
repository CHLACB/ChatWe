from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import threading
import time
from typing import Callable
from uuid import uuid5, NAMESPACE_URL

from wx_ai_assistant.application.context_builder import ContextBuilder
from wx_ai_assistant.application.ai_turn import AiTurnParser
from wx_ai_assistant.application.message_ingestion import MessageIngestionService
from wx_ai_assistant.application.send_queue import SendQueue
from wx_ai_assistant.application.uia_worker import UiaCommandWorker
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus, MessageSource, MessageType, SendTaskStatus, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity, ListenTarget, Message
from wx_ai_assistant.ports.ai_gateway import AiGateway
from wx_ai_assistant.ports.repository import Repository
from wx_ai_assistant.ports.wechat_driver import WechatDriver
from wx_ai_assistant.infrastructure.observability.console import print_error_block


@dataclass
class PendingAiTurn:
    identity: ConversationIdentity
    trigger_message: Message
    trigger_messages: list[Message]
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
        async_ai: bool = False,
        ai_worker_count: int = 2,
        uia_worker: UiaCommandWorker | None = None,
        auto_send_enabled: bool = False,
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
        self.uia_worker = uia_worker
        self.async_ai = async_ai
        self.auto_send_enabled = auto_send_enabled
        self._state_lock = threading.RLock()
        self._ai_executor = ThreadPoolExecutor(max_workers=max(1, ai_worker_count), thread_name_prefix="ai-turn") if async_ai else None
        self._pending_ai_turns: dict[str, PendingAiTurn] = {}
        self._active_ai_turns: dict[str, dict] = {}
        self._recent_trigger_keys: dict[str, float] = {}
        self._last_visible_snapshots: list[dict] = []
        self._last_ai_turns: list[dict] = []
        self._last_ai_errors: list[dict] = []
        self._start_listener: Callable[[str], None] | None = None
        self._stop_listener: Callable[[str, str | None], None] | None = None
        self._poll_once: Callable[[], None] | None = None
        self._listener_snapshot: Callable[[], dict] | None = None
        self._runtime_enqueue: Callable[[str, dict | None], object] | None = None
        self._runtime_snapshot: Callable[[], dict] | None = None

    def initialize(self):
        if self.uia_worker is not None:
            return self.uia_worker.initialize()
        return self.driver.initialize()

    def status(self):
        if self.uia_worker is not None:
            return self.uia_worker.status()
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

    def has_listening_targets(self) -> bool:
        return any(target.status == ListenStatus.LISTENING for target in self.repo.list_listen_targets())

    def delete_listen_target(self, conversation_id: str) -> bool:
        self.repo.set_listen_status(conversation_id, ListenStatus.STOPPED, "deleted")
        with self._state_lock:
            self._pending_ai_turns.pop(conversation_id, None)
            self._active_ai_turns.pop(conversation_id, None)
        return self.repo.delete_listen_target(conversation_id)

    def bind_listener_controls(
        self,
        start_listener: Callable[[str], None],
        stop_listener: Callable[[str, str | None], None],
        poll_once: Callable[[], None] | None = None,
        listener_snapshot: Callable[[], dict] | None = None,
    ) -> None:
        self._start_listener = start_listener
        self._stop_listener = stop_listener
        self._poll_once = poll_once
        self._listener_snapshot = listener_snapshot

    def bind_runtime_worker(
        self,
        enqueue: Callable[[str, dict | None], object],
        snapshot: Callable[[], dict],
    ) -> None:
        self._runtime_enqueue = enqueue
        self._runtime_snapshot = snapshot

    def request_runtime_command(self, kind: str, payload: dict | None = None):
        if self._runtime_enqueue is None:
            return self.execute_runtime_command(kind, payload or {})
        return self._runtime_enqueue(kind, payload)

    def start_listen_target(self, conversation_id: str) -> None:
        if self._start_listener is None:
            raise RuntimeError("监听调度器尚未绑定")
        self._start_listener(conversation_id)

    def request_start_listen_target(self, conversation_id: str):
        return self.request_runtime_command("start_listen_target", {"conversation_id": conversation_id})

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

    def retry_send_task(self, send_task_id: str):
        return self._retry_send_task_direct(send_task_id)

    def request_retry_send_task(self, send_task_id: str):
        return self.request_runtime_command("retry_send_task", {"send_task_id": send_task_id})

    def _retry_send_task_direct(self, send_task_id: str):
        task = self.repo.get_send_task(send_task_id)
        if task is None:
            raise ValueError("发送任务不存在")
        if task.status != SendTaskStatus.FAILED:
            raise ValueError("只有 failed 发送任务可以重试")
        if not self.repo.reset_send_task_for_retry(send_task_id):
            raise ValueError("发送任务状态已变化，无法重试")
        retried = self.repo.get_send_task(send_task_id)
        if retried is None:
            raise ValueError("发送任务不存在")
        return retried

    def clear_conversation_memory(self, conversation_id: str) -> dict[str, int]:
        with self._state_lock:
            self._pending_ai_turns.pop(conversation_id, None)
        return self.repo.clear_conversation_memory(conversation_id)

    def preview_proactive_message(self, conversation_id: str, instruction: str = "") -> dict:
        identity = self.repo.get_conversation(conversation_id)
        if identity is None:
            raise ValueError(f"会话不存在: {conversation_id}")
        generator = getattr(self.ai, "generate_proactive_reply", None)
        if not callable(generator):
            raise RuntimeError("当前 AI 模式不支持联系人主动判断")
        trigger = Message(
            conversation_id=conversation_id,
            sender_type=SenderType.SYSTEM,
            sender_name="system",
            message_type=MessageType.TEXT,
            content=f"主动触达检查：{instruction or '无额外说明'}",
            source=MessageSource.REALTIME,
            message_id="proactive_manual",
        )
        context = self.context_builder.build_context(identity, trigger)
        raw_reply = generator(context=context, identity=identity, instruction=instruction).strip()
        turn = self.ai_turn_parser.parse(raw_reply)
        return {
            "conversation_id": conversation_id,
            "display_name": identity.display_name,
            "messages": turn.messages,
            "done": turn.done,
            "decision": getattr(self.ai, "last_decision_snapshot", None),
            "raw_reply": raw_reply,
        }

    def queue_proactive_message(self, conversation_id: str, instruction: str = "") -> dict:
        preview = self.preview_proactive_message(conversation_id, instruction)
        tasks = [
            self.send_queue.enqueue(conversation_id, message, trigger_message_id="proactive_manual")
            for message in preview.get("messages", [])
        ]
        preview["send_tasks"] = [asdict(task) for task in tasks]
        return preview

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

    def request_poll_listeners_once(self):
        return self.request_runtime_command("poll_listeners_once")

    def current_conversation(self) -> ConversationIdentity | None:
        if self.uia_worker is not None:
            return self.uia_worker.current_conversation()
        with self._driver_guard():
            return self.driver.get_current_conversation()

    def runtime_snapshot(self) -> dict:
        if self._runtime_snapshot is None:
            return {
                "running": False,
                "last_driver_status": None,
                "last_current_conversation": None,
                "last_error": None,
                "recent_commands": [],
            }
        return self._runtime_snapshot()

    def execute_runtime_command(self, kind: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        if kind == "initialize":
            status = self.initialize()
            return {"status": status.__dict__, "driver_status": status.__dict__}
        if kind == "start_listen_target":
            self._restore_wechat_foreground()
            self.start_listen_target(str(payload["conversation_id"]))
            return {"conversation_id": str(payload["conversation_id"])}
        if kind == "retry_send_task":
            self._restore_wechat_foreground()
            task = self._retry_send_task_direct(str(payload["send_task_id"]))
            return {"send_task": asdict(task)}
        if kind == "poll_listeners_once":
            self.poll_listeners_once()
            return {}
        if kind == "current_conversation":
            current = self.current_conversation()
            return {"current_conversation": asdict(current) if current else None}
        if kind == "driver_status":
            status = self.status()
            return {"driver_status": status.__dict__}
        raise ValueError(f"未知运行命令: {kind}")

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
        runtime = self.runtime_snapshot()
        driver_status = runtime.get("last_driver_status") or {
            "ok": False,
            "mode": "unknown",
            "message": "微信运行 Worker 尚未完成自检",
        }
        current = runtime.get("last_current_conversation")

        return {
            "driver_status": driver_status,
            "current_conversation": current,
            "runtime_worker": runtime,
            "listener": self._listener_snapshot() if self._listener_snapshot else {},
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
                    "trigger_message_count": len(pending.trigger_messages),
                    "trigger_messages": [message.content for message in pending.trigger_messages],
                    "age_seconds": round(time.monotonic() - pending.last_other_message_at, 3),
                }
                for pending in list(self._pending_ai_turns.values())
            ],
            "active_ai_turns": list(self._active_ai_turns.values()),
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
        with self._state_lock:
            now = time.monotonic()
            pending = self._pending_ai_turns.get(identity.conversation_id)
            if pending is None:
                trigger_messages = list(triggers)
            else:
                trigger_messages = [*pending.trigger_messages, *triggers]
            msg = self._build_turn_trigger_message(identity, trigger_messages)
            self._pending_ai_turns[identity.conversation_id] = PendingAiTurn(
                identity=identity,
                trigger_message=msg,
                trigger_messages=trigger_messages,
                last_other_message_at=now,
            )

    def flush_ready_ai_turns(self, force: bool = False) -> None:
        now = time.monotonic()
        with self._state_lock:
            ready_ids = [
                conversation_id
                for conversation_id, pending in self._pending_ai_turns.items()
                if conversation_id not in self._active_ai_turns
                and (force or now - pending.last_other_message_at >= self.ai_turn_quiet_seconds)
            ]
            ready_turns = [
                self._pending_ai_turns.pop(conversation_id)
                for conversation_id in ready_ids
                if conversation_id in self._pending_ai_turns
            ]
        for pending in ready_turns:
            if self._ai_executor is not None:
                self._ai_executor.submit(self._generate_ai_turn, pending)
            else:
                self._generate_ai_turn(pending)

    def _generate_ai_turn(self, pending: PendingAiTurn) -> None:
        with self._state_lock:
            self._active_ai_turns[pending.identity.conversation_id] = self._ai_turn_status(pending, "thinking")
        try:
            context = self.context_builder.build_context(pending.identity, pending.trigger_message)
            identity_setter = getattr(self.ai, "set_contact_identity", None)
            if callable(identity_setter):
                identity_setter(pending.identity)
            raw_reply = self.ai.generate_reply(context=context, trigger_message=pending.trigger_message).strip()
            turn = self.ai_turn_parser.parse(raw_reply)
            with self._state_lock:
                self._active_ai_turns[pending.identity.conversation_id] = self._ai_turn_status(
                    pending,
                    "draft_ready",
                    {"parsed_messages": turn.messages, "done": turn.done},
                )
            if self._catch_up_new_messages_before_reply(pending):
                self._record_ai_error(pending.identity, "AI 思考期间收到新消息，已取消旧回复并等待下一轮合并分析。")
                return
            self._record_ai_turn(pending, context, raw_reply, turn.messages, turn.done)
            if not turn.done:
                self._record_ai_error(pending.identity, "AI 未按本轮完成协议输出 done=true，已跳过本轮。")
                return
            if not self.auto_send_enabled:
                with self._state_lock:
                    if self._last_ai_turns:
                        self._last_ai_turns[-1]["auto_send_enabled"] = False
                        self._last_ai_turns[-1]["send_suppressed"] = True
                        self._last_ai_turns[-1]["send_suppressed_reason"] = "auto_send_disabled"
                return
            for reply in turn.messages:
                self.send_queue.enqueue(
                    pending.identity.conversation_id,
                    reply,
                    trigger_message_id=pending.trigger_message.message_id,
                )
        except Exception as exc:
            self._record_ai_error(pending.identity, str(exc))
        finally:
            with self._state_lock:
                self._active_ai_turns.pop(pending.identity.conversation_id, None)

    def _catch_up_new_messages_before_reply(self, pending: PendingAiTurn) -> bool:
        """Read once before enqueueing replies to avoid answering stale turns.

        If the user sent more messages while the AI was thinking, keep those
        messages for the next quiet-window turn and skip the old draft.
        """
        try:
            if self.uia_worker is not None:
                def ingest_verified(messages: list[Message]) -> None:
                    self.handle_realtime_messages(pending.identity, messages)

                self.uia_worker.read_target_messages(pending.identity, on_read=ingest_verified)
                messages = []
            else:
                with self._driver_guard():
                    messages = self.driver.read_visible_text_messages(pending.identity)
        except Exception as exc:
            self._record_ai_error(pending.identity, f"发送前新消息检查失败，继续使用当前草稿: {exc}")
            return False
        with self._state_lock:
            before = self._pending_ai_turns.get(pending.identity.conversation_id)
        if messages:
            self.handle_realtime_messages(pending.identity, messages)
        with self._state_lock:
            after = self._pending_ai_turns.get(pending.identity.conversation_id)
        return before is not None or (after is not None and after is not before)

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

    def _build_turn_trigger_message(self, identity: ConversationIdentity, messages: list[Message]) -> Message:
        if not messages:
            raise ValueError("AI 触发消息不能为空")
        if len(messages) == 1:
            return messages[0]

        last = messages[-1]
        lines = [f"对方连续发来 {len(messages)} 条消息，这是同一轮意思，请合并理解："]
        lines.extend(f"{index}. {message.content}" for index, message in enumerate(messages, 1))
        return Message(
            conversation_id=identity.conversation_id,
            sender_type=last.sender_type,
            sender_name=last.sender_name,
            message_type=last.message_type,
            content="\n".join(lines),
            source=last.source,
            raw_id=last.raw_id,
            created_at=last.created_at,
            received_at=last.received_at,
            message_id="turn_" + last.message_id,
            fingerprint="turn:" + "|".join(message.fingerprint or message.message_id for message in messages),
        )

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

    def _ai_turn_status(self, pending: PendingAiTurn, stage: str, extra: dict | None = None) -> dict:
        status = {
            "conversation_id": pending.identity.conversation_id,
            "display_name": pending.identity.display_name,
            "stage": stage,
            "trigger_message_id": pending.trigger_message.message_id,
            "trigger_content": pending.trigger_message.content,
            "trigger_message_count": len(pending.trigger_messages),
            "trigger_messages": [message.content for message in pending.trigger_messages],
            "at_monotonic": round(time.monotonic(), 3),
        }
        if extra:
            status.update(extra)
        return status

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
            "trigger_message_count": len(pending.trigger_messages),
            "trigger_messages": [message.content for message in pending.trigger_messages],
            "done": done,
            "parsed_messages": parsed_messages,
            "raw_reply": raw_reply,
            "context_tail": context_preview,
            "at_monotonic": round(time.monotonic(), 3),
        }
        if isinstance(decision, dict):
            entry.update(decision)
            entry["trigger_content"] = pending.trigger_message.content
            entry["trigger_message_count"] = len(pending.trigger_messages)
            entry["trigger_messages"] = [message.content for message in pending.trigger_messages]
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

    def shutdown(self) -> None:
        if self._ai_executor is not None:
            self._ai_executor.shutdown(wait=False, cancel_futures=True)

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

    def _restore_wechat_foreground(self) -> None:
        if self.uia_worker is not None:
            self.uia_worker.restore_and_activate()
            return
        restorer = getattr(self.driver, "restore_and_activate", None)
        if not callable(restorer):
            return
        with self._driver_guard():
            status = restorer()
            if not getattr(status, "ok", False):
                raise RuntimeError(getattr(status, "message", "无法激活微信窗口"))
