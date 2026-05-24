from __future__ import annotations

import json
import re
from typing import Any

from wx_ai_assistant.core.text_sanitize import sanitize_text
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import JsonChatClient
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import (
    DraftReplyOutput,
    IntentAnalysisOutput,
    ReplyDecisionOutput,
    ResponsePlanOutput,
    SafetyCheckOutput,
)
from wx_ai_assistant.infrastructure.ai.langgraph_agent.prompts import (
    ANALYZE_INTENT_PROMPT,
    DECIDE_REPLY_PROMPT,
    DRAFT_REPLY_PROMPT,
    PLAN_RESPONSE_PROMPT,
    SAFETY_CHECK_PROMPT,
)
from wx_ai_assistant.infrastructure.ai.langgraph_agent.state import WechatReplyState


IDENTITY_WORDS = ("AI", "ai", "机器人", "自动回复", "助手", "程序", "代替", "替他", "替你")
SERVICE_TONE_WORDS = ("很高兴为您服务", "请问还有什么", "亲", "客服", "为您", "帮助您")


class WechatReplyNodes:
    def __init__(self, client: JsonChatClient, policy_loader=None, profile_loader=None):
        self.client = client
        self.policy_loader = policy_loader
        self.profile_loader = profile_loader

    def load_contact_policy(self, state: WechatReplyState) -> dict[str, Any]:
        if self.policy_loader is None:
            return {"contact_policy": {}}
        policy = self.policy_loader.load_for_identity(state.get("_identity"), str(state.get("display_name", "")))
        return {
            "contact_policy": policy.model_dump(),
            "proactive_mode": policy.proactive_mode,
            "max_messages_per_turn": policy.max_messages_per_turn,
        }

    def load_conversation_profile(self, state: WechatReplyState) -> dict[str, Any]:
        if self.profile_loader is None:
            return {"conversation_profile": {}}
        profile = self.profile_loader.load_for_identity(state.get("_identity"), str(state.get("display_name", "")))
        return {"conversation_profile": profile.model_dump()}

    def analyze_intent(self, state: WechatReplyState) -> dict[str, Any]:
        output = self._validate_output(
            IntentAnalysisOutput,
            self.client.complete_json(ANALYZE_INTENT_PROMPT, self._base_user_prompt(state)),
            state,
            "analyze_intent",
        )
        return {key: sanitize_text(str(value)).strip() for key, value in output.model_dump().items()}

    def decide_reply(self, state: WechatReplyState) -> dict[str, Any]:
        output = self._validate_output(
            ReplyDecisionOutput,
            self.client.complete_json(DECIDE_REPLY_PROMPT, self._base_user_prompt(state, include_analysis=True)),
            state,
            "decide_reply",
        )
        return {
            "should_reply": output.should_reply,
            "no_reply_reason": sanitize_text(output.no_reply_reason).strip(),
        }

    def plan_response(self, state: WechatReplyState) -> dict[str, Any]:
        output = self._validate_output(
            ResponsePlanOutput,
            self.client.complete_json(PLAN_RESPONSE_PROMPT, self._base_user_prompt(state, include_analysis=True)),
            state,
            "plan_response",
        )
        return {"reply_strategy": sanitize_text(output.reply_strategy).strip()}

    def draft_reply(self, state: WechatReplyState) -> dict[str, Any]:
        output = self._validate_output(
            DraftReplyOutput,
            self.client.complete_json(
                DRAFT_REPLY_PROMPT,
                self._base_user_prompt(state, include_analysis=True)
                + f"\n\nmax_messages_per_turn: {self._max_messages(state)}",
            ),
            state,
            "draft_reply",
        )
        max_messages = self._max_messages(state)
        return {"draft_messages": self._coerce_message_list(output.draft_messages)[:max_messages]}

    def auto_safety_check(self, state: WechatReplyState) -> dict[str, Any]:
        raw_draft_messages = self._coerce_message_list(state.get("draft_messages"))
        deterministic = self._deterministic_safety(raw_draft_messages, state)
        if deterministic["safety_action"] != "allow":
            return deterministic
        draft_messages = self._normalize_messages(state.get("draft_messages"), state)
        output = self._validate_output(
            SafetyCheckOutput,
            self.client.complete_json(
                SAFETY_CHECK_PROMPT,
                self._base_user_prompt(state, include_analysis=True)
                + "\n\n草稿消息:\n"
                + json.dumps(draft_messages, ensure_ascii=False),
            ),
            state,
            "auto_safety_check",
        )
        action = output.safety_action.strip().lower()
        if action not in {"allow", "rewrite", "skip"}:
            action = "rewrite"
        reasons = output.safety_reasons
        rewritten = self._normalize_messages(output.rewritten_messages, state)
        if action == "allow":
            final_messages = draft_messages
        elif action == "rewrite":
            final_messages = rewritten or self._rewrite_locally(draft_messages, state)
        else:
            final_messages = []
        profile_checked = self._apply_profile_safety(final_messages, state, action, reasons)
        return {
            "safety_action": profile_checked["safety_action"],
            "safety_reasons": profile_checked["safety_reasons"],
            "final_messages": profile_checked["final_messages"],
        }

    def format_output(self, state: WechatReplyState) -> dict[str, Any]:
        final_messages = [] if not state.get("should_reply", False) else self._normalize_messages(state.get("final_messages"), state)
        raw_output = json.dumps({"messages": final_messages, "done": True}, ensure_ascii=False)
        return {
            "final_messages": final_messages,
            "done": True,
            "raw_output": raw_output,
        }

    def _base_user_prompt(self, state: WechatReplyState, include_analysis: bool = False) -> str:
        lines = [
            f"run_id: {state.get('run_id', '')}",
            f"proactive_mode: {state.get('proactive_mode', 'off')}",
            f"conversation_id: {state.get('conversation_id', '')}",
            f"trigger_message_id: {state.get('trigger_message_id', '')}",
            f"display_name: {state.get('display_name', '')}",
            "\n[联系人策略]",
            json.dumps(state.get("contact_policy") or {}, ensure_ascii=False),
            "\n[会话画像]",
            json.dumps(state.get("conversation_profile") or {}, ensure_ascii=False),
            "\n[上下文]",
            str(state.get("context", "")),
            "\n[触发消息]",
            str(state.get("trigger_message", "")),
        ]
        if include_analysis:
            lines.extend(
                [
                    "\n[已分析字段]",
                    f"intent: {state.get('intent', '')}",
                    f"emotion: {state.get('emotion', '')}",
                    f"user_need: {state.get('user_need', '')}",
                    f"relationship_signal: {state.get('relationship_signal', '')}",
                    f"should_reply: {state.get('should_reply', '')}",
                    f"reply_strategy: {state.get('reply_strategy', '')}",
                ]
            )
        return "\n".join(lines)

    def _validate_output(self, model_cls, data: dict[str, Any], state: WechatReplyState, node_name: str):
        try:
            return model_cls.model_validate(data)
        except Exception as exc:
            errors = list(state.get("node_errors") or [])
            errors.append(f"{node_name}: {exc}")
            state["node_errors"] = errors
            raise

    def _normalize_messages(self, value: Any, state: WechatReplyState) -> list[str]:
        raw_messages = self._coerce_message_list(value)
        max_messages = self._max_messages(state)
        messages: list[str] = []
        for item in raw_messages:
            text = sanitize_text(str(item)).strip()
            text = self._remove_identity_claims(text)
            text = re.sub(r"\s+", " ", text)
            if text:
                messages.append(text)
            if len(messages) >= max_messages:
                break
        return messages

    def _coerce_message_list(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        elif isinstance(value, list):
            return [sanitize_text(str(item)).strip() for item in value if sanitize_text(str(item)).strip()]
        return []

    def _deterministic_safety(self, messages: list[str], state: WechatReplyState) -> dict[str, Any]:
        avoid_topic = self._matched_avoid_topic(messages, state)
        if avoid_topic:
            return {
                "safety_action": "skip",
                "safety_reasons": [f"触碰 avoid_topics: {avoid_topic}"],
                "final_messages": [],
            }
        if any(self._contains_identity_claim(message) for message in messages):
            rewritten = self._rewrite_locally(messages, state)
            if not rewritten:
                return {
                    "safety_action": "skip",
                    "safety_reasons": ["草稿承认或暗示 AI/机器人身份"],
                    "final_messages": [],
                }
            return {
                "safety_action": "rewrite",
                "safety_reasons": ["草稿承认或暗示 AI/机器人身份，已本地改写"],
                "final_messages": rewritten,
            }
        return {"safety_action": "allow", "safety_reasons": [], "final_messages": messages}

    def _rewrite_locally(self, messages: list[str], state: WechatReplyState) -> list[str]:
        rewritten: list[str] = []
        max_messages = self._max_messages(state)
        max_chars = self._max_chars_per_message(state)
        for message in messages:
            text = self._remove_identity_claims(message)
            text = re.sub(r"(当然可以|我很乐意帮助你|作为.*?)[，,。\s]*", "", text)
            for word in SERVICE_TONE_WORDS:
                text = text.replace(word, "")
            text = text.strip(" ，,。")
            text = self._shorten(text, max_chars)
            if text:
                rewritten.append(text)
            if len(rewritten) >= max_messages:
                break
        return rewritten

    def _contains_identity_claim(self, text: str) -> bool:
        return any(word in text for word in IDENTITY_WORDS)

    def _remove_identity_claims(self, text: str) -> str:
        result = text
        replacements = [
            (r"我是\s*(?:AI|ai|机器人|自动回复|助手|程序)[，,。\s]*", ""),
            (r"(?:AI|ai|机器人|自动回复|助手|程序)[，,。\s]*", ""),
            (r"替(?:他|你|用户)?回复[，,。\s]*", ""),
            (r"代替(?:他|你|用户)?回复[，,。\s]*", ""),
        ]
        for pattern, replacement in replacements:
            result = re.sub(pattern, replacement, result)
        return result.strip()

    def _apply_profile_safety(
        self,
        messages: list[str],
        state: WechatReplyState,
        action: str,
        reasons: list[str],
    ) -> dict[str, Any]:
        safety_reasons = [sanitize_text(str(reason)).strip() for reason in reasons if str(reason).strip()]
        avoid_topic = self._matched_avoid_topic(messages, state)
        if avoid_topic:
            return {
                "safety_action": "skip",
                "safety_reasons": [*safety_reasons, f"触碰 avoid_topics: {avoid_topic}"],
                "final_messages": [],
            }
        max_messages = self._max_messages(state)
        max_chars = self._max_chars_per_message(state)
        final_messages: list[str] = []
        rewrote = action == "rewrite"
        for message in messages[:max_messages]:
            text = sanitize_text(str(message)).strip()
            cleaned = self._remove_identity_claims(text)
            if cleaned != text or any(word in cleaned for word in SERVICE_TONE_WORDS):
                cleaned = self._rewrite_locally([cleaned], state)[0] if self._rewrite_locally([cleaned], state) else ""
                rewrote = True
                safety_reasons.append("已本地移除 AI/客服腔表达")
            shortened = self._shorten(cleaned, max_chars)
            if shortened != cleaned:
                rewrote = True
                safety_reasons.append("已按会话画像缩短单条消息")
            if shortened:
                final_messages.append(shortened)
        if len(messages) > max_messages:
            rewrote = True
            safety_reasons.append("已按会话画像截断消息条数")
        if not final_messages:
            return {"safety_action": "skip", "safety_reasons": safety_reasons or ["安全检查后无可发送内容"], "final_messages": []}
        return {
            "safety_action": "rewrite" if rewrote else action,
            "safety_reasons": list(dict.fromkeys(safety_reasons)),
            "final_messages": final_messages,
        }

    def _max_messages(self, state: WechatReplyState) -> int:
        policy_limit = int(state.get("max_messages_per_turn") or 2)
        profile = state.get("conversation_profile") or {}
        profile_limit = profile.get("max_messages") if isinstance(profile, dict) else None
        if isinstance(profile_limit, int) and profile_limit > 0:
            return max(1, min(policy_limit, profile_limit))
        return max(1, policy_limit)

    def _max_chars_per_message(self, state: WechatReplyState) -> int:
        profile = state.get("conversation_profile") or {}
        value = profile.get("max_chars_per_message") if isinstance(profile, dict) else None
        if isinstance(value, int) and value > 0:
            return value
        return 80

    def _shorten(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip(" ，,。")

    def _matched_avoid_topic(self, messages: list[str], state: WechatReplyState) -> str:
        profile = state.get("conversation_profile") or {}
        avoid_topics = profile.get("avoid_topics") if isinstance(profile, dict) else []
        if not isinstance(avoid_topics, list):
            return ""
        haystack = "\n".join([str(state.get("trigger_message", "")), *messages])
        for topic in avoid_topics:
            topic_text = sanitize_text(str(topic)).strip()
            if topic_text and topic_text in haystack:
                return topic_text
        return ""
