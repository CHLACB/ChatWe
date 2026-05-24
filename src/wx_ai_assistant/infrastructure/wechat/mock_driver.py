from __future__ import annotations

import threading
from datetime import datetime, timezone

from wx_ai_assistant.domain.enums import MessageType, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.ports.wechat_driver import DriverStatus, SendResult, WechatDriver


class MockWechatDriver(WechatDriver):
    """Mock driver for architecture testing without WeChat."""

    def __init__(self):
        self._current: ConversationIdentity | None = None
        self._messages: dict[str, list[Message]] = {}
        self._unread_conversation_ids: set[str] = set()
        self.switch_count = 0
        self.switched_conversation_ids: list[str] = []
        self._lock = threading.RLock()

    def initialize(self) -> DriverStatus:
        return DriverStatus(ok=True, mode="mock", message="mock driver initialized")

    def status(self) -> DriverStatus:
        return DriverStatus(ok=True, mode="mock", message="mock driver ready")

    def switch_conversation(self, identity: ConversationIdentity) -> DriverStatus:
        with self._lock:
            self._current = identity
            self._messages.setdefault(identity.conversation_id, [])
            self.switch_count += 1
            self.switched_conversation_ids.append(identity.conversation_id)
        return DriverStatus(ok=True, mode="mock", message=f"switched to {identity.display_name}")

    def find_active_listen_targets(self, targets: list[ConversationIdentity]) -> list[ConversationIdentity]:
        with self._lock:
            return [target for target in targets if target.conversation_id in self._unread_conversation_ids]

    def get_current_conversation(self) -> ConversationIdentity | None:
        with self._lock:
            return self._current

    def read_visible_text_messages(self, identity: ConversationIdentity) -> list[Message]:
        with self._lock:
            self._unread_conversation_ids.discard(identity.conversation_id)
            return list(self._messages.get(identity.conversation_id, []))[-30:]

    def send_text(self, identity: ConversationIdentity, content: str) -> SendResult:
        with self._lock:
            if self._current is None or self._current.conversation_id != identity.conversation_id:
                return SendResult(ok=False, message="mock current conversation mismatch")
            self._messages.setdefault(identity.conversation_id, []).append(Message(
                conversation_id=identity.conversation_id,
                sender_type=SenderType.SELF,
                sender_name="self",
                message_type=MessageType.TEXT,
                content=content,
            ))
        return SendResult(ok=True, message="sent")

    def inject_other_text(self, identity: ConversationIdentity, content: str, sender_name: str = "other") -> Message:
        """Test helper. Not part of production driver."""
        with self._lock:
            msg = Message(
                conversation_id=identity.conversation_id,
                sender_type=SenderType.OTHER,
                sender_name=sender_name,
                message_type=MessageType.TEXT,
                content=content,
            )
            self._messages.setdefault(identity.conversation_id, []).append(msg)
            self._unread_conversation_ids.add(identity.conversation_id)
            return msg

    def clear_unread(self, identity: ConversationIdentity) -> None:
        with self._lock:
            self._unread_conversation_ids.discard(identity.conversation_id)

    def mark_unread(self, identity: ConversationIdentity) -> None:
        with self._lock:
            self._unread_conversation_ids.add(identity.conversation_id)
