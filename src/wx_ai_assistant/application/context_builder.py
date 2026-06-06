from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.domain.enums import MessageType
from wx_ai_assistant.ports.history_reader import HistoryReader
from wx_ai_assistant.ports.repository import Repository


class ContextBuilder:
    """Placeholder context strategy.

    You said historical context will be handled separately. This layer is therefore
    intentionally replaceable. The current implementation only creates a readable
    text context for initial integration.
    """

    def __init__(self, repo: Repository, history_reader: HistoryReader):
        self.repo = repo
        self.history_reader = history_reader

    def build_context(self, identity: ConversationIdentity, trigger_message: Message) -> str:
        recent = self.repo.list_recent_messages(identity.conversation_id, limit=30)
        history = self.history_reader.read_history(identity, limit=100)

        lines: list[str] = []
        lines.append(f"当前会话: {identity.display_name} ({identity.conversation_type.value})")
        if history.ok:
            lines.append("\n[历史消息摘要输入 - 当前仅原样拼接，后续可替换]")
            for m in history.messages[-20:]:
                lines.append(f"{m.sender_type.value}:{m.sender_name or ''}: {self._message_content_for_context(m)}")
        else:
            lines.append(f"\n[历史读取失败: {history.error}]")

        lines.append("\n[最近实时消息]")
        for m in recent:
            lines.append(f"{m.sender_type.value}:{m.sender_name or ''}: {self._message_content_for_context(m)}")

        lines.append("\n[当前触发消息]")
        lines.append(self._message_content_for_context(trigger_message))
        return "\n".join(lines)

    def _message_content_for_context(self, message: Message) -> str:
        if message.message_type == MessageType.TEXT:
            return message.content
        label = {
            MessageType.IMAGE: "图片",
            MessageType.STICKER: "表情包",
            MessageType.VOICE: "语音",
        }.get(message.message_type, "非文本消息")
        description = message.media_description or message.content
        return f"[{label}] {description}".strip()
