from __future__ import annotations

import hashlib
from datetime import datetime

from wx_ai_assistant.domain.enums import MessageSource, MessageType, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.identity.verifier import ConversationVerifier
from wx_ai_assistant.application.media_recognition import MediaRecognitionService
from wx_ai_assistant.ports.repository import Repository
from wx_ai_assistant.ports.wechat_driver import WechatDriver
from wx_ai_assistant.core.text_sanitize import sanitize_text


TRIGGERABLE_MESSAGE_TYPES = {MessageType.TEXT, MessageType.IMAGE, MessageType.STICKER, MessageType.VOICE}


class MessageIngestionService:
    def __init__(
        self,
        repo: Repository,
        driver: WechatDriver,
        verifier: ConversationVerifier,
        media_recognition: MediaRecognitionService | None = None,
    ):
        self.repo = repo
        self.driver = driver
        self.verifier = verifier
        self.media_recognition = media_recognition or MediaRecognitionService()

    def ingest_realtime_messages(self, identity: ConversationIdentity, messages: list[Message]) -> list[Message]:
        """Store new messages and return messages that should trigger AI."""
        current = self._current_for_ingest(identity)
        self.verifier.verify_before_ingest(identity, current)

        triggerable_ids = {id(msg) for msg in self._messages_after_last_self(messages)}
        trigger_messages: list[Message] = []
        for msg in messages:
            msg.conversation_id = identity.conversation_id
            msg = self.media_recognition.recognize(msg)
            msg.content = sanitize_text(msg.content)
            if msg.sender_name:
                msg.sender_name = sanitize_text(msg.sender_name)
            if self._is_duplicate_visible_self(identity, msg):
                continue
            if self._is_duplicate_visible_other_media(identity, msg):
                continue
            if not msg.fingerprint:
                msg.fingerprint = self._fingerprint(msg)
            inserted = self.repo.insert_message_if_new(msg)
            if (
                inserted
                and id(msg) in triggerable_ids
                and msg.sender_type == SenderType.OTHER
                and msg.message_type in TRIGGERABLE_MESSAGE_TYPES
                and msg.content.strip()
            ):
                trigger_messages.append(msg)
        return trigger_messages

    def ingest_baseline_messages(self, identity: ConversationIdentity, messages: list[Message]) -> int:
        """Store visible messages when a listener starts, but never trigger AI."""
        current = self._current_for_ingest(identity)
        self.verifier.verify_before_ingest(identity, current)

        inserted_count = 0
        for msg in messages:
            msg.conversation_id = identity.conversation_id
            msg = self.media_recognition.recognize(msg)
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

    def _messages_after_last_self(self, messages: list[Message]) -> list[Message]:
        """Only messages after the latest visible self message can trigger AI.

        UIA visible items do not expose stable message IDs. After sending a reply,
        older friend messages may move on screen and receive a new UI fingerprint.
        Treating the visible self message as a watermark prevents those old
        messages from opening another AI turn.
        """
        last_self_index = -1
        for index, msg in enumerate(messages):
            if msg.sender_type == SenderType.SELF:
                last_self_index = index
        if last_self_index < 0:
            return messages
        return messages[last_self_index + 1 :]

    def _is_duplicate_visible_self(self, identity: ConversationIdentity, msg: Message) -> bool:
        if msg.sender_type != SenderType.SELF or msg.message_type not in TRIGGERABLE_MESSAGE_TYPES:
            return False
        content = " ".join(msg.content.split())
        if not content:
            return False
        for recent in reversed(self.repo.list_recent_messages(identity.conversation_id, limit=20)):
            if recent.sender_type != SenderType.SELF or recent.message_type not in TRIGGERABLE_MESSAGE_TYPES:
                continue
            if " ".join(recent.content.split()) == content:
                return True
        return False

    def _is_duplicate_visible_other_media(self, identity: ConversationIdentity, msg: Message) -> bool:
        if msg.sender_type != SenderType.OTHER or msg.message_type not in {MessageType.IMAGE, MessageType.STICKER}:
            return False
        content = " ".join(msg.content.split())
        if not content:
            return False
        for recent in reversed(self.repo.list_recent_messages(identity.conversation_id, limit=30)):
            if recent.sender_type != SenderType.OTHER or recent.message_type != msg.message_type:
                continue
            if " ".join(recent.content.split()) == content:
                return True
        return False
