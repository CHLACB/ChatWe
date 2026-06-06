from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Callable

from wx_ai_assistant.domain.enums import ListenStatus, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.application.uia_worker import UiaCommandWorker
from wx_ai_assistant.identity.verifier import ConversationVerifier
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
        transient_error_limit: int = 3,
        auto_start_worker: bool = True,
        scan_interval_seconds: float | None = None,
        uia_worker: UiaCommandWorker | None = None,
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
        self.uia_worker = uia_worker or UiaCommandWorker(driver, ConversationVerifier(), self._driver_lock)
        self._baselined_conversation_ids: set[str] = set()
        self._startup_baseline_ids: list[str] = []
        self._round_robin_cursor = 0
        self._last_scan_at: dict[str, float] = {}
        self._pending_active_ids: list[str] = []
        self._processing_conversation_id: str | None = None
        self._processing_reason: str | None = None
        self._last_active_ids: list[str] = []
        self._last_locked_conversation_id: str | None = None
        self._transient_error_counts: dict[str, int] = {}
        self._visible_message_counts: dict[str, Counter[str]] = {}
        self.debug_logging = debug_logging
        self.transient_error_limit = max(1, transient_error_limit)
        self.auto_start_worker = auto_start_worker
        self.scan_interval_seconds = max(0.2, scan_interval_seconds if scan_interval_seconds is not None else poll_interval_seconds)

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
        if conversation_id in self._startup_baseline_ids:
            self._startup_baseline_ids.remove(conversation_id)
        self._startup_baseline_ids.append(conversation_id)
        self._last_scan_at.pop(conversation_id, None)
        self._visible_message_counts.pop(conversation_id, None)
        if self.auto_start_worker:
            self.start_worker()

    def stop_target(self, conversation_id: str, reason: str | None = None) -> None:
        self.repo.set_listen_status(conversation_id, ListenStatus.STOPPED, reason)
        self._transient_error_counts.pop(conversation_id, None)
        if conversation_id in self._startup_baseline_ids:
            self._startup_baseline_ids.remove(conversation_id)
        self._last_scan_at.pop(conversation_id, None)

    def resume_target(self, conversation_id: str) -> None:
        """Resume a transiently failed target without clearing its baseline."""
        self.repo.set_listen_status(conversation_id, ListenStatus.LISTENING, None)
        self._transient_error_counts.pop(conversation_id, None)
        if self.auto_start_worker:
            self.start_worker()

    def poll_once(self) -> None:
        targets = [t for t in self.repo.list_listen_targets() if t.status == ListenStatus.LISTENING]
        target_by_id = {target.conversation.conversation_id: target for target in targets}
        baseline_targets = self._requested_baseline_targets(targets)
        if baseline_targets:
            self._log("baseline_start", details={"count": len(baseline_targets)})
        active_targets = self._find_active_targets(targets)
        self._enqueue_active_targets(active_targets)
        if active_targets:
            self._last_locked_conversation_id = active_targets[0].conversation.conversation_id
            self._log(
                "unread_detected",
                action="enqueue",
                details={"active_targets": len(active_targets), "queue": len(self._pending_active_ids)},
            )
        elif targets and not baseline_targets:
            self._log("no_active_targets", details={"listening_targets": len(targets), "queue": len(self._pending_active_ids)})

        work_items = []
        queued_target = self._pop_next_queued_target(target_by_id)
        if queued_target is not None:
            work_items.append((queued_target, "active"))
        elif baseline_targets:
            work_items.append((baseline_targets[0], "baseline"))

        for target, read_reason in work_items:
            try:
                self._log("read_target_task", target=target.conversation.display_name, details={"reason": read_reason})
                self._processing_conversation_id = target.conversation.conversation_id
                self._processing_reason = read_reason
                active_ids = {active.conversation.conversation_id for active in active_targets}

                def handle_verified_read(messages: list[Message]) -> None:
                    if target.conversation.conversation_id not in self._baselined_conversation_ids:
                        if read_reason == "active" or target.conversation.conversation_id in active_ids:
                            baseline_messages, realtime_messages = self._split_new_messages_for_unbaselined_unread(messages)
                            self.on_baseline_messages(target.conversation, baseline_messages)
                            if realtime_messages:
                                self._message_snapshot(target.conversation.display_name, realtime_messages)
                                self.on_messages(target.conversation, realtime_messages)
                        else:
                            self.on_baseline_messages(target.conversation, messages)
                        self._baselined_conversation_ids.add(target.conversation.conversation_id)
                        self._remove_startup_baseline(target.conversation.conversation_id)
                        self._remember_visible_messages(target.conversation.conversation_id, messages)
                        self._log(
                            "baseline_done",
                            target=target.conversation.display_name,
                            details={"messages": len(messages)},
                        )
                    elif messages:
                        new_messages = self._visible_delta(target.conversation.conversation_id, messages)
                        if new_messages:
                            self._message_snapshot(target.conversation.display_name, new_messages)
                            self.on_messages(target.conversation, new_messages)
                    self._clear_target_error(target.conversation.conversation_id)
                    self._last_scan_at[target.conversation.conversation_id] = time.monotonic()

                self.uia_worker.read_target_messages(target.conversation, on_read=handle_verified_read)
            except Exception as exc:
                self._handle_target_error(target.conversation.conversation_id, str(exc))
                self._log(
                    "target_error",
                    target=target.conversation.display_name,
                    details={"error": str(exc)},
                )
            finally:
                if self._processing_conversation_id == target.conversation.conversation_id:
                    self._processing_conversation_id = None
                    self._processing_reason = None
        if self.on_after_poll:
            self.on_after_poll()

    def snapshot(self) -> dict:
        targets = {target.conversation.conversation_id: target for target in self.repo.list_listen_targets()}
        return {
            "pending_active_ids": list(self._pending_active_ids),
            "pending_active_targets": [
                {
                    "conversation_id": conversation_id,
                    "display_name": targets[conversation_id].conversation.display_name if conversation_id in targets else conversation_id,
                }
                for conversation_id in self._pending_active_ids
            ],
            "processing_conversation_id": self._processing_conversation_id,
            "processing_reason": self._processing_reason,
            "processing_target": (
                {
                    "conversation_id": self._processing_conversation_id,
                    "display_name": targets[self._processing_conversation_id].conversation.display_name,
                }
                if self._processing_conversation_id in targets
                else None
            ),
            "last_active_ids": list(self._last_active_ids),
            "last_locked_conversation_id": self._last_locked_conversation_id,
            "last_locked_target": (
                {
                    "conversation_id": self._last_locked_conversation_id,
                    "display_name": targets[self._last_locked_conversation_id].conversation.display_name,
                }
                if self._last_locked_conversation_id in targets
                else None
            ),
            "target_states": [
                {
                    "conversation_id": target.conversation.conversation_id,
                    "display_name": target.conversation.display_name,
                    "baselined": target.conversation.conversation_id in self._baselined_conversation_ids,
                    "queued": target.conversation.conversation_id in self._pending_active_ids,
                    "processing": target.conversation.conversation_id == self._processing_conversation_id,
                    "last_read_age_seconds": self._last_read_age_seconds(target.conversation.conversation_id),
                    "visible_fingerprint_count": sum(self._visible_message_counts.get(target.conversation.conversation_id, Counter()).values()),
                    "transient_error_count": self._transient_error_counts.get(target.conversation.conversation_id, 0),
                }
                for target in targets.values()
            ],
            "uia_worker": self.uia_worker.snapshot(),
        }

    def _find_active_targets(self, targets) -> list:
        if not targets:
            return []
        self._log("passive_scan", details={"targets": len(targets)})
        active_conversations = self.uia_worker.scan_left_list([target.conversation for target in targets])
        active_ids = {identity.conversation_id for identity in active_conversations}
        active_targets = [target for target in targets if target.conversation.conversation_id in active_ids]
        self._last_active_ids = [target.conversation.conversation_id for target in active_targets]
        return active_targets

    def _enqueue_active_targets(self, targets) -> None:
        queued = set(self._pending_active_ids)
        for target in targets:
            conversation_id = target.conversation.conversation_id
            if conversation_id == self._processing_conversation_id or conversation_id in queued:
                continue
            self._pending_active_ids.append(conversation_id)
            queued.add(conversation_id)

    def _pop_next_queued_target(self, target_by_id: dict[str, object]):
        while self._pending_active_ids:
            conversation_id = self._pending_active_ids.pop(0)
            target = target_by_id.get(conversation_id)
            if target is not None:
                return target
        return None

    def _requested_baseline_targets(self, targets) -> list:
        if not targets:
            return []
        target_by_id = {target.conversation.conversation_id: target for target in targets}
        requested = [
            target_by_id[conversation_id]
            for conversation_id in self._startup_baseline_ids
            if conversation_id in target_by_id and conversation_id not in self._baselined_conversation_ids
        ]
        if not requested:
            requested = [
                target
                for target in targets
                if target.conversation.conversation_id not in self._baselined_conversation_ids
            ]
        # Baseline at most one target per poll. This avoids A2/A4 competing for
        # the foreground in the same cycle and prevents one target's failed
        # switch from poisoning another target's visible-message read.
        return requested[:1]

    def _remove_startup_baseline(self, conversation_id: str) -> None:
        if conversation_id in self._startup_baseline_ids:
            self._startup_baseline_ids.remove(conversation_id)

    def _split_new_messages_for_unbaselined_unread(self, messages: list[Message]) -> tuple[list[Message], list[Message]]:
        """Use WeChat's new-message divider to avoid losing first unread turns.

        A target can receive unread messages before its first baseline poll. In
        that case treating the whole visible window as baseline drops the new
        message. WeChat inserts a visible "以下为新消息" system divider for this
        situation, so everything after it is safe to process as realtime.
        """
        divider_index = -1
        for index, message in enumerate(messages):
            content = " ".join((message.content or "").split())
            if message.sender_type == SenderType.SYSTEM and "以下为新消息" in content:
                divider_index = index
        if divider_index < 0:
            return self._split_tail_other_messages_for_unbaselined_unread(messages)
        return messages[: divider_index + 1], messages[divider_index + 1 :]

    def _split_tail_other_messages_for_unbaselined_unread(self, messages: list[Message]) -> tuple[list[Message], list[Message]]:
        """Fallback when WeChat exposes unread state but no new-message divider.

        On some WeChat builds the first unread turn after listener startup has a
        red dot in the left list but no visible "以下为新消息" divider in the chat
        pane. Treat the contiguous tail of OTHER messages as realtime so the
        first message does not get swallowed by baseline.
        """
        tail_start = len(messages)
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].sender_type != SenderType.OTHER:
                break
            tail_start = index
        if tail_start >= len(messages):
            return messages, []
        return messages[:tail_start], messages[tail_start:]

    def _next_target_by_cursor(self, targets):
        if not targets:
            return None
        index = self._round_robin_cursor % len(targets)
        target = targets[index]
        self._round_robin_cursor = (index + 1) % len(targets)
        return target

    def _identity_matches(self, expected: ConversationIdentity, actual: ConversationIdentity) -> bool:
        expected_names = {expected.display_name, expected.remark_name, expected.local_id} - {None, ""}
        actual_names = {actual.display_name, actual.remark_name, actual.local_id} - {None, ""}
        return expected.conversation_id == actual.conversation_id or bool(expected_names & actual_names)

    def _same_target(self, first, second) -> bool:
        return first.conversation.conversation_id == second.conversation.conversation_id

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

    def _last_read_age_seconds(self, conversation_id: str) -> float | None:
        last_read_at = self._last_scan_at.get(conversation_id)
        if last_read_at is None:
            return None
        return round(time.monotonic() - last_read_at, 3)

    def _remember_visible_messages(self, conversation_id: str, messages: list[Message]) -> None:
        self._visible_message_counts[conversation_id] = Counter(self._visible_key(message) for message in messages)

    def _visible_delta(self, conversation_id: str, messages: list[Message]) -> list[Message]:
        previous = self._visible_message_counts.get(conversation_id, Counter())
        current: Counter[str] = Counter()
        emitted: list[Message] = []
        for message in messages:
            key = self._visible_key(message)
            current[key] += 1
            if current[key] > previous.get(key, 0):
                emitted.append(message)
        self._visible_message_counts[conversation_id] = current
        return emitted

    def _visible_key(self, message: Message) -> str:
        content = " ".join((message.content or "").split())
        return "|".join([message.sender_type.value, message.message_type.value, content])

    def _clear_target_error(self, conversation_id: str) -> None:
        self._transient_error_counts.pop(conversation_id, None)
        self.repo.set_listen_status(conversation_id, ListenStatus.LISTENING, None)

    def _handle_target_error(self, conversation_id: str, error: str) -> None:
        if self._is_identity_deferred_error(error):
            self.repo.set_listen_status(
                conversation_id,
                ListenStatus.LISTENING,
                f"{error}；当前窗口不是目标会话，已跳过本轮读取，下轮继续尝试，避免串聊。",
            )
            return
        if self._is_transient_error(error):
            count = self._transient_error_counts.get(conversation_id, 0) + 1
            self._transient_error_counts[conversation_id] = count
            if count < self.transient_error_limit:
                self.repo.set_listen_status(
                    conversation_id,
                    ListenStatus.LISTENING,
                    f"{error}；临时 UIA 失败，正在重试 {count}/{self.transient_error_limit - 1}",
                )
                return
        self.stop_target(conversation_id, error)

    def _is_identity_deferred_error(self, error: str) -> bool:
        return (
            "读取消息前会话验证失败" in error
            or "读取前会话验证失败" in error
            or "入库前会话验证失败" in error
        )

    def _is_transient_error(self, error: str) -> bool:
        markers = [
            "search_box",
            "搜索框",
            "Ctrl+F",
            "焦点未落到左侧搜索框",
            "切换会话后无法读取当前聊天标题",
            "无法读取当前会话身份",
            "未找到 chat_title 控件",
            "未找到 message_list 控件",
            "未找到 input_box 控件",
        ]
        return any(marker in error for marker in markers)
