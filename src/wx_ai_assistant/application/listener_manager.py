from __future__ import annotations

import threading
import time
from typing import Callable

from wx_ai_assistant.domain.enums import ListenStatus
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.infrastructure.observability.console import print_listener_event, print_message_snapshot
from wx_ai_assistant.ports.repository import Repository
from wx_ai_assistant.ports.wechat_driver import WechatDriver


class ListenerManager:
    """Polls listen targets using passive detection before switching chats."""

    def __init__(
        self,
        repo: Repository,
        driver: WechatDriver,
        poll_interval_seconds: float,
        on_messages: Callable[[ConversationIdentity, list[Message]], None],
        on_baseline_messages: Callable[[ConversationIdentity, list[Message]], None] | None = None,
        on_after_poll: Callable[[], None] | None = None,
        driver_lock: threading.RLock | None = None,
        debug_logging: bool = False,
    ):
        self.repo = repo
        self.driver = driver
        self.poll_interval_seconds = poll_interval_seconds
        self.on_messages = on_messages
        self.on_baseline_messages = on_baseline_messages or on_messages
        self.on_after_poll = on_after_poll
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._driver_lock = driver_lock or threading.RLock()
        self._baselined_conversation_ids: set[str] = set()
        self.debug_logging = debug_logging

    def start_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="listener-manager", daemon=True)
        self._thread.start()

    def stop_worker(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def start_target(self, conversation_id: str) -> None:
        self.repo.set_listen_status(conversation_id, ListenStatus.LISTENING, None)
        self._baselined_conversation_ids.discard(conversation_id)
        self.start_worker()

    def stop_target(self, conversation_id: str, reason: str | None = None) -> None:
        self.repo.set_listen_status(conversation_id, ListenStatus.STOPPED, reason)

    def poll_once(self) -> None:
        targets = [t for t in self.repo.list_listen_targets() if t.status == ListenStatus.LISTENING]
        baseline_targets = [
            target for target in targets if target.conversation.conversation_id not in self._baselined_conversation_ids
        ]
        if baseline_targets:
            self._log("baseline_start", details={"count": len(baseline_targets)})
        active_targets = self._find_active_targets([
            target for target in targets if target.conversation.conversation_id in self._baselined_conversation_ids
        ])
        if active_targets:
            self._log(
                "unread_detected",
                action="switch_and_read",
                details={"active_targets": len(active_targets)},
            )
        elif targets and not baseline_targets:
            self._log("no_active_targets", details={"listening_targets": len(targets)})

        for target in [*baseline_targets, *active_targets]:
            try:
                self._log("switch_and_read", target=target.conversation.display_name)
                with self._driver_lock:
                    status = self.driver.switch_conversation(target.conversation)
                    if not status.ok:
                        raise RuntimeError(status.message)
                    messages = self.driver.read_visible_text_messages(target.conversation)
                    if target.conversation.conversation_id not in self._baselined_conversation_ids:
                        self.on_baseline_messages(target.conversation, messages)
                        self._baselined_conversation_ids.add(target.conversation.conversation_id)
                        self._log(
                            "baseline_done",
                            target=target.conversation.display_name,
                            details={"messages": len(messages)},
                        )
                    elif messages:
                        self._message_snapshot(target.conversation.display_name, messages)
                        self.on_messages(target.conversation, messages)
            except Exception as exc:
                self.stop_target(target.conversation.conversation_id, str(exc))
                self._log(
                    "target_error",
                    target=target.conversation.display_name,
                    details={"error": str(exc)},
                )
        if self.on_after_poll:
            self.on_after_poll()

    def _find_active_targets(self, targets) -> list:
        if not targets:
            return []
        self._log("passive_scan", details={"targets": len(targets)})
        active_conversations = self.driver.find_active_listen_targets([target.conversation for target in targets])
        active_ids = {identity.conversation_id for identity in active_conversations}
        return [target for target in targets if target.conversation.conversation_id in active_ids]

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            time.sleep(self.poll_interval_seconds)

    def _log(
        self,
        event: str,
        target: str | None = None,
        action: str | None = None,
        details: dict | None = None,
    ) -> None:
        if self.debug_logging:
            print_listener_event(event, target=target, action=action, details=details)

    def _message_snapshot(self, target: str, messages: list[Message]) -> None:
        if self.debug_logging:
            print_message_snapshot(target, messages)
