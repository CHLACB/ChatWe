from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.ports.ai_gateway import AiGateway


class DummyAiGateway(AiGateway):
    """Safe default: no reply.

    Change this to EchoAiGateway for local pipeline testing, or implement a real AI gateway.
    """

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        return ""


class EchoAiGateway(AiGateway):
    """Development helper only."""

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        return f"收到：{trigger_message.content}"
