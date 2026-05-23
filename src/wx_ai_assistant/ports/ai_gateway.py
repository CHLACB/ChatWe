from typing import Protocol

from wx_ai_assistant.domain.models import Message


class AiGateway(Protocol):
    def generate_reply(self, context: str, trigger_message: Message) -> str:
        """Return final text to send. Empty string means do not send."""
        ...
