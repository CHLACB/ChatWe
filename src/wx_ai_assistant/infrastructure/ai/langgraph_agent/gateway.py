from __future__ import annotations

import json
from typing import Any
from pathlib import Path
from uuid import uuid4

from wx_ai_assistant.core.text_sanitize import sanitize_jsonable, sanitize_text
from wx_ai_assistant.domain.models import AiDecisionLog, ConversationIdentity, Message
from wx_ai_assistant.infrastructure.ai.langgraph_agent.contact_policy import ContactPolicyLoader
from wx_ai_assistant.infrastructure.ai.langgraph_agent.conversation_profile import ConversationProfileLoader
from wx_ai_assistant.infrastructure.ai.langgraph_agent.graph import build_wechat_reply_graph
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import (
    JsonChatClient,
    LangGraphAiConfig,
    OpenAICompatibleJsonClient,
)
from wx_ai_assistant.infrastructure.ai.langgraph_agent.state import WechatReplyState
from wx_ai_assistant.infrastructure.observability.console import print_error_block
from wx_ai_assistant.ports.ai_gateway import AiGateway
from wx_ai_assistant.ports.repository import Repository


class LangGraphAiGateway(AiGateway):
    """AiGateway implementation backed by a LangGraph node flow.

    The graph only decides and formats reply text. It never sends WeChat
    messages, touches the database, or changes listener targets.
    """

    def __init__(
        self,
        config: LangGraphAiConfig,
        client: JsonChatClient | None = None,
        graph: Any | None = None,
        repository: Repository | None = None,
        policy_loader: ContactPolicyLoader | None = None,
        profile_loader: ConversationProfileLoader | None = None,
    ):
        self.config = config
        self.client = client or OpenAICompatibleJsonClient(config)
        self.repository = repository
        self.policy_loader = policy_loader or ContactPolicyLoader(Path(config.contact_policies_path))
        self.profile_loader = profile_loader or ConversationProfileLoader(Path(config.conversation_profiles_path))
        self.graph = graph or build_wechat_reply_graph(
            self.client,
            policy_loader=self.policy_loader,
            profile_loader=self.profile_loader,
        )
        self._identity: ConversationIdentity | None = None
        self.last_decision_snapshot: dict[str, Any] | None = None

    def set_contact_identity(self, identity: ConversationIdentity) -> None:
        self._identity = identity

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        run_id = "lg_" + uuid4().hex
        identity = self._identity
        state: WechatReplyState = {
            "run_id": run_id,
            "context": sanitize_text(context),
            "trigger_message_id": trigger_message.message_id,
            "trigger_message": sanitize_text(trigger_message.content),
            "conversation_id": trigger_message.conversation_id,
            "display_name": sanitize_text((identity.display_name if identity else trigger_message.sender_name) or ""),
            "remark_name": sanitize_text((identity.remark_name if identity else "") or ""),
            "local_id": sanitize_text((identity.local_id if identity else "") or ""),
            "_identity": identity,
            "proactive_mode": self.config.proactive_mode,
            "max_messages_per_turn": self.config.max_messages_per_turn,
            "done": False,
            "node_errors": [],
        }
        result = self.graph.invoke(state)
        messages = result.get("final_messages", [])
        if isinstance(messages, str):
            messages = [messages]
        if not isinstance(messages, list):
            messages = []
        normalized = [sanitize_text(str(message)).strip() for message in messages if sanitize_text(str(message)).strip()]
        payload = {"messages": normalized[: max(1, self.config.max_messages_per_turn)], "done": True}
        snapshot = self._decision_snapshot(result, payload)
        self.last_decision_snapshot = snapshot
        self._save_decision_log(snapshot)
        return json.dumps(sanitize_jsonable(payload), ensure_ascii=False)

    def _decision_snapshot(self, result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        raw_state = {k: v for k, v in result.items() if not k.startswith("_")}
        return {
            "run_id": result.get("run_id", ""),
            "conversation_id": result.get("conversation_id", ""),
            "trigger_message_id": result.get("trigger_message_id", ""),
            "trigger_message": result.get("trigger_message", ""),
            "display_name": result.get("display_name", ""),
            "contact_policy": result.get("contact_policy") or {},
            "conversation_profile": result.get("conversation_profile") or {},
            "intent": result.get("intent", ""),
            "emotion": result.get("emotion", ""),
            "user_need": result.get("user_need", ""),
            "relationship_signal": result.get("relationship_signal", ""),
            "should_reply": bool(result.get("should_reply", False)),
            "no_reply_reason": result.get("no_reply_reason", ""),
            "reply_strategy": result.get("reply_strategy", ""),
            "draft_messages": result.get("draft_messages") or [],
            "safety_action": result.get("safety_action", ""),
            "safety_reasons": result.get("safety_reasons") or [],
            "final_messages": payload.get("messages") or [],
            "done": bool(payload.get("done", True)),
            "node_errors": result.get("node_errors") or [],
            "raw_state": raw_state,
            "raw_state_json": raw_state,
        }

    def _save_decision_log(self, snapshot: dict[str, Any]) -> None:
        if self.repository is None:
            return
        try:
            self.repository.save_ai_decision_log(AiDecisionLog(**snapshot))
        except Exception as exc:
            print_error_block(
                "AI DECISION LOG WARNING",
                exc,
                {"run_id": snapshot.get("run_id", ""), "target": snapshot.get("display_name", "")},
            )
