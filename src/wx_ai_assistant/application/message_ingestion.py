from __future__ import annotations

import hashlib
from datetime import datetime

from wx_ai_assistant.domain.enums import MessageSource, MessageType, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.identity.verifier import ConversationVerifier
from wx_ai_assistant.ports.repository import Repository
from wx_ai_assistant.ports.wechat_driver import WechatDriver
from wx_ai_assistant.core.text_sanitize import sanitize_text


class MessageIngestionService:
    def __init__(self, repo: Repository, driver: WechatDriver, verifier: ConversationVerifier):
        self.repo = repo
        self.driver = driver
        self.verifier = verifier

    def ingest_realtime_messages(self, identity: ConversationIdentity, messages: list[Message]) -> list[Message]:
        """Store new messages and return messages that should trigger AI."""
        current = self._current_for_ingest(identity)
        self.verifier.verify_before_ingest(identity, current)

        trigger_messages: list[Message] = []
        for msg in messages:
            msg.conversation_id = identity.conversation_id
            msg.content = sanitize_text(msg.content)
            if msg.sender_name:
                msg.sender_name = sanitize_text(msg.sender_name)
            if not msg.fingerprint:
                msg.fingerprint = self._fingerprint(msg)
            inserted = self.repo.insert_message_if_new(msg)
            if inserted and msg.sender_type == SenderType.OTHER and msg.message_type == MessageType.TEXT:
                trigger_messages.append(msg)
        return trigger_messages

    def ingest_baseline_messages(self, identity: ConversationIdentity, messages: list[Message]) -> int:
        """Store visible messages when a listener starts, but never trigger AI."""
        current = self._current_for_ingest(identity)
        self.verifier.verify_before_ingest(identity, current)

        inserted_count = 0
        for msg in messages:
            msg.conversation_id = identity.conversation_id
            msg.content = sanitize_text(msg.content)
            if msg.sender_name:
                msg.sender_name = sanitize_text(msg.sender_name)
            if not msg.fingerprint:
                msg.fingerprint = self._fingerprint(msg)
            if self.repo.insert_message_if_new(msg):
                inserted_count += 1
        return inserted_count

    def insert_sent_message(self, identity: ConversationIdentity, content: str) -> Message:
        msg = Message(
            conversation_id=identity.conversation_id,
            sender_type=SenderType.SELF,
            sender_name="self",
            message_type=MessageType.TEXT,
            content=content,
            source=MessageSource.SENT,
        )
        msg.content = sanitize_text(msg.content)
        msg.fingerprint = self._fingerprint(msg)
        self.repo.insert_message_if_new(msg)
        return msg

    def _fingerprint(self, msg: Message) -> str:
        # Time window deliberately coarse to avoid UIA runtime-id instability.
        minute = msg.created_at.strftime("%Y-%m-%dT%H:%M") if isinstance(msg.created_at, datetime) else "unknown"
        raw = "|".join([
            msg.conversation_id,
            msg.sender_type.value,
            msg.sender_name or "",
            msg.message_type.value,
            msg.content.strip(),
            minute,
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _current_for_ingest(self, identity: ConversationIdentity) -> ConversationIdentity | None:
        getter = getattr(self.driver, "get_current_conversation_for_ingest", None)
        if callable(getter):
            return getter(identity)
        return self.driver.get_current_conversation()
