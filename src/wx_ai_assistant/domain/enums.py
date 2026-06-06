try:
    from enum import StrEnum
except ImportError:  # Python 3.10 compatibility.
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class ConversationType(StrEnum):
    FRIEND = "friend"
    GROUP = "group"


class ListenStatus(StrEnum):
    LISTENING = "listening"
    STOPPED = "stopped"


class SenderType(StrEnum):
    SELF = "self"
    OTHER = "other"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    STICKER = "sticker"
    VOICE = "voice"
    UNSUPPORTED = "unsupported"


class MessageSource(StrEnum):
    REALTIME = "realtime"
    HISTORY = "history"
    SENT = "sent"


class SendTaskStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SUCCESS = "success"
    FAILED = "failed"
