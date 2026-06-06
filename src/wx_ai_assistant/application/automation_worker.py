from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
import threading
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from wx_ai_assistant.application.app_service import WechatApplicationService


@dataclass
class AutomationCommand:
    command_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    message: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WechatRuntimeWorker:
    """Single command worker for UI-affecting actions requested by Web/API.

    The web layer should enqueue commands and read snapshots. It must not call
    UIA driver methods directly during page refreshes or button handlers.
    """

    def __init__(
        self,
        app_service: "WechatApplicationService",
        history_limit: int = 50,
        poll_interval_seconds: float = 1.0,
    ):
        self.app_service = app_service
        self.history_limit = max(10, history_limit)
        self.poll_interval_seconds = max(0.2, poll_interval_seconds)
        self._queue: Queue[AutomationCommand] = Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._commands: list[AutomationCommand] = []
        self._last_driver_status: dict[str, Any] | None = None
        self._last_current_conversation: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._heartbeat_at: datetime | None = None
        self._last_poll_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="wechat-runtime-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def enqueue(self, kind: str, payload: dict[str, Any] | None = None) -> AutomationCommand:
        command = AutomationCommand(command_id="cmd_" + uuid4().hex, kind=kind, payload=payload or {})
        with self._lock:
            self._commands.append(command)
            self._commands = self._commands[-self.history_limit :]
        self._queue.put(command)
        return command

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = [self._command_to_dict(command) for command in self._commands[-20:]]
            pending = sum(1 for command in self._commands if command.status in {"queued", "running"})
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "pending_commands": pending,
                "heartbeat_at": self._heartbeat_at.isoformat() if self._heartbeat_at else None,
                "last_driver_status": self._last_driver_status,
                "last_current_conversation": self._last_current_conversation,
                "last_error": self._last_error,
                "recent_commands": recent,
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                self._heartbeat_at = datetime.now(timezone.utc)
            try:
                command = self._queue.get(timeout=0.2)
            except Empty:
                self._poll_if_due()
                continue
            self._execute(command)
            self._poll_if_due()

    def _poll_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_poll_at < self.poll_interval_seconds:
            return
        self._last_poll_at = now
        try:
            if not self.app_service.has_listening_targets():
                return
            self._execute_internal("poll_listeners_once")
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)

    def _execute(self, command: AutomationCommand) -> None:
        with self._lock:
            command.status = "running"
            command.started_at = datetime.now(timezone.utc)
        try:
            result = self.app_service.execute_runtime_command(command.kind, command.payload)
            with self._lock:
                command.status = "success"
                command.message = "done"
                command.result = result or {}
                command.finished_at = datetime.now(timezone.utc)
                self._last_error = None
                self._update_runtime_snapshots(command.kind, command.result)
        except Exception as exc:
            with self._lock:
                command.status = "failed"
                command.error = str(exc)
                command.finished_at = datetime.now(timezone.utc)
                self._last_error = str(exc)

    def _execute_internal(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        try:
            result = self.app_service.execute_runtime_command(kind, payload or {})
            with self._lock:
                self._last_error = None
                self._update_runtime_snapshots(kind, result)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)

    def _update_runtime_snapshots(self, kind: str, result: dict[str, Any] | None) -> None:
        if not result:
            return
        if "driver_status" in result:
            self._last_driver_status = result["driver_status"]
        if "current_conversation" in result:
            self._last_current_conversation = result["current_conversation"]
        if kind == "initialize" and "status" in result:
            self._last_driver_status = result["status"]

    def _command_to_dict(self, command: AutomationCommand) -> dict[str, Any]:
        data = asdict(command)
        for key in ("created_at", "started_at", "finished_at"):
            value = data.get(key)
            data[key] = value.isoformat() if value else None
        return data
