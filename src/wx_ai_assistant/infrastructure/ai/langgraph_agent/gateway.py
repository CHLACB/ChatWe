from __future__ import annotations

import json
from typing import Any

from wx_ai_assistant.core.text_sanitize import sanitize_jsonable, sanitize_text
from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.infrastructure.ai.langgraph_agent.graph import build_wechat_reply_graph
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import (
    JsonChatClient,
    LangGraphAiConfig,
    OpenAICompatibleJsonClient,
)
from wx_ai_assistant.infrastructure.ai.langgraph_agent.state import WechatReplyState
from wx_ai_assistant.ports.ai_gateway import AiGateway


class LangGraphAiGateway(AiGateway):
    """AiGateway implementation backed by a LangGraph node flow.

    The graph only decides and formats reply text. It never sends WeChat
    messages, touches the database, or changes listener targets.
    """

    def __init__(self, config: LangGraphAiConfig, client: JsonChatClient | None = None, graph: Any | None = None):
        self.config = config
        self.client = client or OpenAICompatibleJsonClient(config)
        self.graph = graph or build_wechat_reply_graph(self.client)

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        state: WechatReplyState = {
            "context": sanitize_text(context),
            "trigger_message": sanitize_text(trigger_message.content),
            "conversation_id": trigger_message.conversation_id,
            "display_name": sanitize_text(trigger_message.sender_name or ""),
            "proactive_mode": self.config.proactive_mode,
            "max_messages_per_turn": self.config.max_messages_per_turn,
            "done": False,
        }
        result = self.graph.invoke(state)
        messages = result.get("final_messages", [])
        if isinstance(messages, str):
            messages = [messages]
        if not isinstance(messages, list):
            messages = []
        normalized = [sanitize_text(str(message)).strip() for message in messages if sanitize_text(str(message)).strip()]
        payload = {"messages": normalized[: max(1, self.config.max_messages_per_turn)], "done": True}
        return json.dumps(sanitize_jsonable(payload), ensure_ascii=False)
