from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from wx_ai_assistant.domain.enums import SendTaskStatus
from wx_ai_assistant.domain.models import ConversationIdentity, SendTask
from wx_ai_assistant.application.uia_worker import UiaCommandWorker
from wx_ai_assistant.identity.verifier import ConversationVerifier
from wx_ai_assistant.infrastructure.observability.console import print_send_event
from wx_ai_assistant.ports.repository import Repository
from wx_ai_assistant.ports.wechat_driver import WechatDriver


class SendQueue:
    """Single worker for all sends.

    WeChat UI operations must be serialized. AI/application code should only create
    send tasks; it must not call driver.send_text directly.
    """

    def __init__(
        self,
        repo: Repository,
        driver: WechatDriver,
        verifier: ConversationVerifier,
        on_failed: Optional[Callable[[str, str], None]] = None,
        on_sent: Optional[Callable[[ConversationIdentity, str], None]] = None,
        driver_lock: threading.RLock | None = None,
        uia_worker: UiaCommandWorker | None = None,
    ):
        self.repo = repo
        self.driver = driver
        self.verifier = verifier
        self.on_failed = on_failed
        self.on_sent = on_sent
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._driver_lock = driver_lock or threading.RLock()
        self.uia_worker = uia_worker or UiaCommandWorker(driver, verifier, self._driver_lock)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="send-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def enqueue(self, conversation_id: str, content: str, trigger_message_id: str | None = None) -> SendTask:
        task = SendTask(conversation_id=conversation_id, content=content, trigger_message_id=trigger_message_id)
        self.repo.create_send_task(task)
        return task

    def _run(self) -> None:
        while not self._stop.is_set():
            tasks = self.repo.list_pending_send_tasks(limit=5)
            if not tasks:
                time.sleep(0.3)
                continue
            for task in tasks:
                self._process(task)

    def _process(self, task: SendTask) -> None:
        identity = self.repo.get_conversation(task.conversation_id)
        if identity is None:
            self.repo.update_send_task(task.send_task_id, SendTaskStatus.FAILED, "会话不存在")
            print_send_event(task.conversation_id, "failed", [task.content], "会话不存在")
            return

        self.repo.update_send_task(task.send_task_id, SendTaskStatus.SENDING)
        try:
            self.uia_worker.driver = self.driver
            self.uia_worker.send_to_target(identity, task.content, on_sent=self.on_sent)
            self.repo.update_send_task(task.send_task_id, SendTaskStatus.SUCCESS)
            print_send_event(identity.display_name, "success", [task.content])
        except Exception as exc:
            error = str(exc)
            self.repo.update_send_task(task.send_task_id, SendTaskStatus.FAILED, error)
            print_send_event(identity.display_name, "failed", [task.content], error)
            if self.on_failed:
                self.on_failed(task.conversation_id, error)
