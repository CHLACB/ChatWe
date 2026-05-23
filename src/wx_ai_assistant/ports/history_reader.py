from dataclasses import dataclass
from typing import Protocol

from wx_ai_assistant.domain.models import ConversationIdentity, Message


@dataclass
class HistoryResult:
    ok: bool
    messages: list[Message]
    error: str | None = None


class HistoryReader(Protocol):
    def read_history(self, identity: ConversationIdentity, limit: int = 100) -> HistoryResult:
        ...
