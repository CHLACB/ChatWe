from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from .enums import ConversationType, ListenStatus, MessageType, SenderType, MessageSource, SendTaskStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass
class ConversationIdentity:
    conversation_id: str
    conversation_type: ConversationType
    display_name: str
    remark_name: Optional[str] = None
    local_id: Optional[str] = None
    last_verified_at: Optional[datetime] = None

    def stable_key(self) -> str:
        if self.local_id:
            return f"{self.conversation_type}:{self.local_id}"
        name = self.remark_name or self.display_name
        return f"{self.conversation_type}:name:{name}"


@dataclass
class ListenTarget:
    conversation: ConversationIdentity
    status: ListenStatus = ListenStatus.STOPPED
    last_error: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Message:
    conversation_id: str
    sender_type: SenderType
    message_type: MessageType
    content: str
    sender_name: Optional[str] = None
    source: MessageSource = MessageSource.REALTIME
    raw_id: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    received_at: datetime = field(default_factory=utc_now)
    message_id: str = field(default_factory=lambda: new_id("msg"))
    fingerprint: Optional[str] = None


@dataclass
class AiResponse:
    conversation_id: str
    trigger_message_id: str
    response_text: str
    created_at: datetime = field(default_factory=utc_now)
    ai_response_id: str = field(default_factory=lambda: new_id("ai"))


@dataclass
class SendTask:
    conversation_id: str
    content: str
    trigger_message_id: Optional[str] = None
    status: SendTaskStatus = SendTaskStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    sent_at: Optional[datetime] = None
    error_message: Optional[str] = None
    send_task_id: str = field(default_factory=lambda: new_id("send"))
