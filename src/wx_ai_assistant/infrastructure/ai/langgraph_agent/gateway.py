from __future__ import annotations

import json
from typing import Any
from pathlib import Path
from uuid import uuid4

from wx_ai_assistant.core.text_sanitize import sanitize_jsonable, sanitize_text
from wx_ai_assistant.domain.models import AiDecisionLog, ConversationIdentity, Message
from wx_ai_assistant.infrastructure.ai.langgraph_agent.graph import build_wechat_reply_graph
from wx_ai_assistant.infrastructure.ai.langgraph_agent.nodes import WechatReplyNodes
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import (
    JsonChatClient,
    LangGraphAiConfig,
    OpenAICompatibleJsonClient,
)
from wx_ai_assistant.infrastructure.ai.langgraph_agent.node_settings import LangGraphNodeSettingsLoader
from wx_ai_assistant.infrastructure.ai.prompt_library import load_prompt_extensions, load_prompt_text
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
        node_settings_loader: LangGraphNodeSettingsLoader | None = None,
    ):
        self.config = config
        self.client = client or OpenAICompatibleJsonClient(config)
        self.repository = repository
        self.node_settings_loader = node_settings_loader or LangGraphNodeSettingsLoader(Path(config.node_settings_path))
        self.graph = graph or build_wechat_reply_graph(
            self.client,
            node_settings_loader=self.node_settings_loader,
        )
        self._identity: ConversationIdentity | None = None
        self.last_decision_snapshot: dict[str, Any] | None = None

    def set_contact_identity(self, identity: ConversationIdentity) -> None:
        self._identity = identity

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        run_id = "lg_" + uuid4().hex
        identity = self._identity
        node_settings = self.node_settings_loader.load()
        system_prompt = load_prompt_text(Path(self.config.system_prompt_path))
        prompt_extensions = load_prompt_extensions(Path(self.config.prompt_extensions_path))
        compact = self._compact_context(context, node_settings.semantic.recent_message_limit, node_settings.semantic.context_summary_max_chars)
        state: WechatReplyState = {
            "run_id": run_id,
            "context": compact["context"],
            "context_summary": compact["context_summary"],
            "recent_messages": compact["recent_messages"],
            "trigger_message_id": trigger_message.message_id,
            "trigger_message": sanitize_text(trigger_message.content),
            "trigger_message_type": trigger_message.message_type.value,
            "conversation_id": trigger_message.conversation_id,
            "display_name": sanitize_text((identity.display_name if identity else trigger_message.sender_name) or ""),
            "remark_name": sanitize_text((identity.remark_name if identity else "") or ""),
            "local_id": sanitize_text((identity.local_id if identity else "") or ""),
            "_identity": identity,
            "proactive_mode": self.config.proactive_mode,
            "max_messages_per_turn": self.config.max_messages_per_turn,
            "system_prompt": system_prompt,
            "prompt_extensions": prompt_extensions,
            "media_observations": [],
            "risk_flags": [],
            "requires_safety_model": False,
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

    def generate_proactive_reply(self, context: str, identity: ConversationIdentity, instruction: str = "") -> str:
        run_id = "lg_proactive_" + uuid4().hex
        node_settings = self.node_settings_loader.load()
        system_prompt = load_prompt_text(Path(self.config.system_prompt_path))
        prompt_extensions = load_prompt_extensions(Path(self.config.prompt_extensions_path))
        compact = self._compact_context(context, node_settings.semantic.recent_message_limit, node_settings.semantic.context_summary_max_chars)
        state: WechatReplyState = {
            "run_id": run_id,
            "context": compact["context"],
            "context_summary": compact["context_summary"],
            "recent_messages": compact["recent_messages"],
            "trigger_message_id": "proactive_manual",
            "trigger_message": sanitize_text(instruction or "联系人主动触达检查"),
            "trigger_message_type": "proactive",
            "conversation_id": identity.conversation_id,
            "display_name": sanitize_text(identity.display_name or ""),
            "remark_name": sanitize_text(identity.remark_name or ""),
            "local_id": sanitize_text(identity.local_id or ""),
            "_identity": identity,
            "proactive_mode": self.config.proactive_mode,
            "max_messages_per_turn": min(1, self.config.max_messages_per_turn),
            "system_prompt": system_prompt,
            "prompt_extensions": prompt_extensions,
            "media_observations": [],
            "risk_flags": [],
            "requires_safety_model": False,
            "done": False,
            "node_errors": [],
        }
        nodes = WechatReplyNodes(
            self.client,
            node_settings_loader=self.node_settings_loader,
        )
        for loader in (nodes.load_node_settings, nodes.retrieve_memory_context):
            state.update(loader(state))
        decision = nodes.proactive_send_decision(state)
        state.update(decision)
        if not state.get("should_reply", False):
            payload = {"messages": [], "done": True}
            snapshot = self._decision_snapshot(state, payload)
            self.last_decision_snapshot = snapshot
            self._save_decision_log(snapshot)
            return json.dumps(sanitize_jsonable(payload), ensure_ascii=False)
        checked = nodes.rule_safety_check(state)
        state.update(checked)
        final_messages = nodes._normalize_messages(state.get("final_messages") or state.get("draft_messages"), state)[:1]
        payload = {"messages": final_messages, "done": True}
        snapshot = self._decision_snapshot(state, payload)
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
            "node_settings": result.get("node_settings") or {},
            "intent": result.get("intent", ""),
            "emotion": result.get("emotion", ""),
            "user_need": result.get("user_need", ""),
            "relationship_signal": result.get("relationship_signal", ""),
            "should_reply": bool(result.get("should_reply", False)),
            "no_reply_reason": result.get("no_reply_reason", ""),
            "reply_strategy": result.get("reply_strategy", ""),
            "risk_flags": result.get("risk_flags") or [],
            "requires_safety_model": bool(result.get("requires_safety_model", False)),
            "media_observations": result.get("media_observations") or [],
            "retrieved_memories": result.get("retrieved_memories") or [],
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
            allowed = AiDecisionLog.__dataclass_fields__.keys()
            self.repository.save_ai_decision_log(AiDecisionLog(**{k: v for k, v in snapshot.items() if k in allowed}))
        except Exception as exc:
            print_error_block(
                "AI DECISION LOG WARNING",
                exc,
                {"run_id": snapshot.get("run_id", ""), "target": snapshot.get("display_name", "")},
            )

    def _compact_context(self, context: str, recent_limit: int = 8, summary_max_chars: int = 500) -> dict[str, Any]:
        """Keep graph state small: summary + last 8 message lines only.

        Full history must not flow through every LangGraph node. Later vector
        memory can append compact retrieval snippets to context_summary.
        """
        text = sanitize_text(context)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        recent_start = 0
        for index, line in enumerate(lines):
            if line.startswith("[最近实时消息]"):
                recent_start = index + 1
        recent_lines: list[str] = []
        for line in lines[recent_start:]:
            if line.startswith("[当前触发消息]"):
                break
            if ":" in line and not line.startswith("["):
                recent_lines.append(line)
        recent_messages = recent_lines[-max(1, recent_limit):]
        summary_parts = []
        for line in lines:
            if line.startswith("当前会话:") or line.startswith("[历史读取失败:"):
                summary_parts.append(line)
            if len(summary_parts) >= 2:
                break
        context_summary = "\n".join(summary_parts)[:max(1, summary_max_chars)]
        compact_context = "\n".join([context_summary, "[最近消息窗口]", *recent_messages]).strip()
        return {
            "context": compact_context,
            "context_summary": context_summary,
            "recent_messages": recent_messages,
        }
