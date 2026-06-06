from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
import threading
from typing import Any, Callable
from uuid import uuid4

from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.identity.verifier import ConversationVerifier
from wx_ai_assistant.ports.wechat_driver import WechatDriver


@dataclass
class UiaCommand:
    command_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    target: ConversationIdentity | None = None
    status: str = "queued"
    error: str | None = None
    result: Any = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    done: threading.Event = field(default_factory=threading.Event, repr=False)


class UiaCommandWorker:
    """The single execution lane for all WeChat UIA operations."""

    def __init__(
        self,
        driver: WechatDriver,
        verifier: ConversationVerifier,
        driver_lock: threading.RLock | None = None,
        history_limit: int = 80,
    ):
        self.driver = driver
        self.verifier = verifier
        self._driver_lock = driver_lock or threading.RLock()
        self.history_limit = max(20, history_limit)
        self._queue: Queue[UiaCommand] = Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.RLock()
        self._commands: list[UiaCommand] = []
        self._current: UiaCommand | None = None
        self._worker_thread_id: int | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="uia-command-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def submit(self, kind: str, payload: dict[str, Any] | None = None, target: ConversationIdentity | None = None) -> Any:
        command = UiaCommand(
            command_id="uia_" + uuid4().hex,
            kind=kind,
            payload=payload or {},
            target=target,
        )
        with self._state_lock:
            self._commands.append(command)
            self._commands = self._commands[-self.history_limit :]

        if self._thread and self._thread.is_alive() and threading.get_ident() != self._worker_thread_id:
            self._queue.put(command)
            command.done.wait()
        else:
            self._execute(command)

        if command.status == "failed":
            raise RuntimeError(command.error or "UIA command failed")
        return command.result

    def initialize(self):
        return self.submit("initialize")

    def status(self):
        return self.submit("driver_status")

    def current_conversation(self):
        return self.submit("current_conversation")

    def restore_and_activate(self):
        return self.submit("restore_and_activate")

    def scan_left_list(self, targets: list[ConversationIdentity]) -> list[ConversationIdentity]:
        return self.submit("scan_left_list", {"targets": targets})

    def read_target_messages(
        self,
        identity: ConversationIdentity,
        on_read: Callable[[list[Message]], Any] | None = None,
    ) -> list[Message]:
        return self.submit("read_target_messages", {"on_read": on_read}, target=identity)

    def send_to_target(
        self,
        identity: ConversationIdentity,
        content: str,
        on_sent: Callable[[ConversationIdentity, str], None] | None = None,
    ) -> None:
        self.submit("send_to_target", {"content": content, "on_sent": on_sent}, target=identity)

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            queued = [self._command_to_dict(command) for command in self._commands if command.status == "queued"]
            current = self._command_to_dict(self._current) if self._current else None
            recent = [self._command_to_dict(command) for command in self._commands[-20:]]
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "current_task": current,
            "queued_tasks": queued,
            "recent_tasks": recent,
        }

    def _run(self) -> None:
        self._worker_thread_id = threading.get_ident()
        while not self._stop.is_set():
            try:
                command = self._queue.get(timeout=0.2)
            except Empty:
                continue
            self._execute(command)

    def _execute(self, command: UiaCommand) -> None:
        with self._state_lock:
            self._current = command
            command.status = "running"
            command.started_at = datetime.now(timezone.utc)
        try:
            with self._driver_lock:
                command.result = self._execute_under_lock(command)
            with self._state_lock:
                command.status = "success"
                command.finished_at = datetime.now(timezone.utc)
        except Exception as exc:
            with self._state_lock:
                command.status = "failed"
                command.error = str(exc)
                command.finished_at = datetime.now(timezone.utc)
        finally:
            with self._state_lock:
                if self._current is command:
                    self._current = None
            command.done.set()

    def _execute_under_lock(self, command: UiaCommand) -> Any:
        if command.kind == "initialize":
            return self.driver.initialize()
        if command.kind == "driver_status":
            return self.driver.status()
        if command.kind == "current_conversation":
            return self.driver.get_current_conversation()
        if command.kind == "restore_and_activate":
            restorer = getattr(self.driver, "restore_and_activate", None)
            if not callable(restorer):
                return None
            status = restorer()
            if not getattr(status, "ok", False):
                raise RuntimeError(getattr(status, "message", "无法激活微信窗口"))
            return status
        if command.kind == "scan_left_list":
            return self.driver.find_active_listen_targets(command.payload.get("targets") or [])
        if command.kind == "verify_current_target":
            identity = self._require_target(command)
            current = self.driver.get_current_conversation()
            result = self.verifier.identity_matches(identity, current)
            if not result.ok:
                raise RuntimeError(result.reason)
            return current
        if command.kind == "switch_to_target":
            identity = self._require_target(command)
            self._switch_and_verify(identity, "切换后会话验证失败")
            return self.driver.get_current_conversation()
        if command.kind == "read_target_messages":
            identity = self._require_target(command)
            self._switch_and_verify(identity, "读取前会话验证失败")
            messages = self.driver.read_visible_text_messages(identity)
            self._verify_current(identity, "入库前会话验证失败")
            on_read = command.payload.get("on_read")
            if callable(on_read):
                on_read(messages)
            self._verify_current(identity, "读取后会话验证失败")
            return messages
        if command.kind == "send_to_target":
            identity = self._require_target(command)
            content = str(command.payload.get("content") or "")
            self.verifier.verify_before_send(self.driver, identity)
            result = self.driver.send_text(identity, content)
            if not result.ok:
                raise RuntimeError(result.message)
            self.verifier.verify_after_send(self.driver, identity, content)
            on_sent = command.payload.get("on_sent")
            if callable(on_sent):
                on_sent(identity, content)
            return None
        raise ValueError(f"未知 UIA 命令: {command.kind}")

    def _switch_and_verify(self, identity: ConversationIdentity, prefix: str) -> None:
        status = self.driver.switch_conversation(identity)
        if not status.ok:
            raise RuntimeError(status.message)
        self._verify_current(identity, prefix)

    def _verify_current(self, identity: ConversationIdentity, prefix: str) -> None:
        current = self.driver.get_current_conversation()
        result = self.verifier.identity_matches(identity, current)
        if not result.ok:
            raise RuntimeError(f"{prefix}: {result.reason}")

    def _require_target(self, command: UiaCommand) -> ConversationIdentity:
        if command.target is None:
            raise ValueError(f"{command.kind} 缺少目标会话")
        return command.target

    def _command_to_dict(self, command: UiaCommand) -> dict[str, Any]:
        target = command.target
        data: dict[str, Any] = {
            "command_id": command.command_id,
            "kind": command.kind,
            "payload": {key: value for key, value in command.payload.items() if not callable(value)},
            "status": command.status,
            "error": command.error,
            "created_at": command.created_at,
            "started_at": command.started_at,
            "finished_at": command.finished_at,
        }
        data["target"] = (
            {
                "conversation_id": target.conversation_id,
                "display_name": target.display_name,
            }
            if target
            else None
        )
        if isinstance(command.result, list):
            data["result"] = {"count": len(command.result)}
        elif hasattr(command.result, "__dict__"):
            data["result"] = command.result.__dict__
        else:
            data["result"] = command.result
        for key in ("created_at", "started_at", "finished_at"):
            value = data.get(key)
            data[key] = value.isoformat() if value else None
        return data
