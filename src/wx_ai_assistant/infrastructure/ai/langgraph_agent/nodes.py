from __future__ import annotations

import json
import re
from typing import Any

from wx_ai_assistant.core.text_sanitize import sanitize_text
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import JsonChatClient
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import (
    DraftReplyOutput,
    MediaUnderstandingOutput,
    ProactiveSendDecisionOutput,
    SafetyCheckOutput,
    SemanticReplyDecisionOutput,
)
from wx_ai_assistant.infrastructure.ai.langgraph_agent.prompts import (
    DRAFT_REPLY_PROMPT,
    MEDIA_UNDERSTANDING_PROMPT,
    PROACTIVE_SEND_DECISION_PROMPT,
    SAFETY_CHECK_PROMPT,
    SEMANTIC_REPLY_DECISION_PROMPT,
)
from wx_ai_assistant.infrastructure.ai.langgraph_agent.state import WechatReplyState


IDENTITY_WORDS = ("AI", "ai", "机器人", "自动回复", "助手", "程序", "代替", "替他", "替你")
SERVICE_TONE_WORDS = ("很高兴为您服务", "请问还有什么", "亲", "客服", "为您", "帮助您")
RISK_KEYWORDS = (
    "钱",
    "转账",
    "借钱",
    "付款",
    "收款",
    "红包",
    "银行卡",
    "账号",
    "密码",
    "验证码",
    "身份证",
    "隐私",
    "手机号",
    "银行卡号",
    "地址",
    "照片",
    "私密照",
    "见面",
    "酒店",
    "开房",
)
MEDIA_MARKERS = ("[图片", "[表情", "[语音", "[文件", "图片识别", "表情包识别", "语音转写", "文件")


class WechatReplyNodes:
    def __init__(self, client: JsonChatClient, node_settings_loader=None):
        self.client = client
        self.node_settings_loader = node_settings_loader

    def load_node_settings(self, state: WechatReplyState) -> dict[str, Any]:
        if self.node_settings_loader is None:
            return {"node_settings": {}}
        return {"node_settings": self.node_settings_loader.load().model_dump()}

    def retrieve_memory_context(self, state: WechatReplyState) -> dict[str, Any]:
        settings = self._node_settings(state).get("memory_retrieval") or {}
        if settings.get("enabled") is False:
            return {"retrieved_memories": []}
        return {"retrieved_memories": []}

    def media_understanding(self, state: WechatReplyState) -> dict[str, Any]:
        """Only runs for media/file turns and keeps the output compact.

        Actual OCR/VLM/STT happens before LangGraph in MediaRecognitionService.
        This node only turns the already recognized media description into a
        concise observation for the semantic decision prompt.
        """
        media_settings = self._node_settings(state).get("media_understanding") or {}
        if media_settings.get("enabled") is False or not self._has_media_turn(state):
            return {"media_observations": []}
        media_text = self._media_text(state)
        if not media_text:
            return {"media_observations": []}
        try:
            output = self._validate_output(
                MediaUnderstandingOutput,
                self.client.complete_json(MEDIA_UNDERSTANDING_PROMPT, self._base_user_prompt(state)),
                state,
                "media_understanding",
            )
            observations = self._coerce_message_list(output.media_observations)
        except Exception:
            observations = [self._shorten(media_text, 120)]
        max_observations = int(media_settings.get("max_observations") or 3)
        return {"media_observations": observations[:max(1, max_observations)]}

    def semantic_reply_decision(self, state: WechatReplyState) -> dict[str, Any]:
        output = self._validate_output(
            SemanticReplyDecisionOutput,
            self.client.complete_json(SEMANTIC_REPLY_DECISION_PROMPT, self._base_user_prompt(state)),
            state,
            "semantic_reply_decision",
        )
        risk_flags = self._risk_flags(state, self._coerce_message_list(output.risk_flags))
        return {
            "intent": sanitize_text(output.intent).strip(),
            "emotion": sanitize_text(output.emotion).strip(),
            "user_need": sanitize_text(output.user_need).strip(),
            "relationship_signal": sanitize_text(output.relationship_signal).strip(),
            "should_reply": output.should_reply,
            "no_reply_reason": sanitize_text(output.no_reply_reason).strip(),
            "reply_strategy": sanitize_text(output.reply_strategy).strip(),
            "risk_flags": risk_flags,
            "requires_safety_model": bool(risk_flags),
        }

    def proactive_send_decision(self, state: WechatReplyState) -> dict[str, Any]:
        if not self._policy_allows_proactive(state):
            return {
                "should_reply": False,
                "no_reply_reason": "全局主动模式未开启",
                "reply_strategy": "",
                "risk_flags": [],
                "requires_safety_model": False,
                "draft_messages": [],
                "final_messages": [],
            }
        output = self._validate_output(
            ProactiveSendDecisionOutput,
            self.client.complete_json(PROACTIVE_SEND_DECISION_PROMPT, self._base_user_prompt(state)),
            state,
            "proactive_send_decision",
        )
        risk_flags = self._risk_flags(state, self._coerce_message_list(output.risk_flags))
        message = sanitize_text(output.suggested_message).strip()
        should_send = bool(output.should_send and message and not risk_flags)
        return {
            "intent": "主动触达判断",
            "emotion": "",
            "user_need": "无新消息，检查是否允许轻度主动",
            "relationship_signal": "",
            "should_reply": should_send,
            "no_reply_reason": "" if should_send else sanitize_text(output.no_send_reason or "当前不适合主动").strip(),
            "reply_strategy": sanitize_text(output.strategy).strip(),
            "risk_flags": risk_flags,
            "requires_safety_model": bool(risk_flags),
            "draft_messages": [message] if should_send else [],
        }

    def draft_reply(self, state: WechatReplyState) -> dict[str, Any]:
        output = self._validate_output(
            DraftReplyOutput,
            self.client.complete_json(
                DRAFT_REPLY_PROMPT,
                self._base_user_prompt(state, include_decision=True)
                + f"\n\nmax_messages_per_turn: {self._max_messages(state)}",
            ),
            state,
            "draft_reply",
        )
        max_messages = self._max_messages(state)
        return {"draft_messages": self._coerce_message_list(output.draft_messages)[:max_messages]}

    def rule_safety_check(self, state: WechatReplyState) -> dict[str, Any]:
        messages = self._coerce_message_list(state.get("draft_messages"))
        deterministic = self._deterministic_safety(messages, state)
        if deterministic["safety_action"] != "allow":
            return {**deterministic, "requires_safety_model": False}
        normalized = self._normalize_messages(messages, state)
        checked = self._apply_profile_safety(normalized, state, "allow", [])
        if state.get("requires_safety_model", False):
            return {**checked, "requires_safety_model": True}
        return {**checked, "requires_safety_model": False}

    def model_safety_check(self, state: WechatReplyState) -> dict[str, Any]:
        draft_messages = self._normalize_messages(state.get("final_messages") or state.get("draft_messages"), state)
        output = self._validate_output(
            SafetyCheckOutput,
            self.client.complete_json(
                SAFETY_CHECK_PROMPT,
                self._base_user_prompt(state, include_decision=True)
                + "\n\n风险标记:\n"
                + json.dumps(state.get("risk_flags") or [], ensure_ascii=False)
                + "\n\n草稿消息:\n"
                + json.dumps(draft_messages, ensure_ascii=False),
            ),
            state,
            "model_safety_check",
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

    def _base_user_prompt(self, state: WechatReplyState, include_decision: bool = False) -> str:
        lines = [
            f"run_id: {state.get('run_id', '')}",
            f"proactive_mode: {state.get('proactive_mode', 'off')}",
            f"conversation_id: {state.get('conversation_id', '')}",
            f"trigger_message_id: {state.get('trigger_message_id', '')}",
            f"trigger_message_type: {state.get('trigger_message_type', 'text')}",
            f"display_name: {state.get('display_name', '')}",
            "\n[系统提示词]",
            sanitize_text(str(state.get("system_prompt", ""))).strip(),
            "\n[节点参数摘要]",
            self._compact_json(
                self._node_settings(state).get("reply_strategy") or {},
                keys=(
                    "default_max_messages",
                    "default_max_chars_per_message",
                    "question_policy",
                    "initiative_level",
                    "ending_style",
                    "community_reply_policy",
                ),
            ),
            "\n[独立扩展提示词]",
            self._prompt_extensions_text(state),
            "\n[主动触达控制]",
            self._compact_json(
                self._node_settings(state).get("proactive") or {},
                keys=("enabled", "default_mode", "manual_trigger_only", "cooldown_minutes", "max_messages_per_day", "decision_policy"),
            ),
            "\n[最近上下文摘要]",
            str(state.get("context_summary", "")),
            "\n[最近消息窗口]",
            "\n".join(self._recent_messages(state)),
            "\n[相关记忆]",
            "\n".join(self._coerce_message_list(state.get("retrieved_memories"))),
            "\n[媒体观察]",
            "\n".join(self._coerce_message_list(state.get("media_observations"))[:3]),
            "\n[触发消息]",
            str(state.get("trigger_message", "")),
        ]
        if include_decision:
            lines.extend(
                [
                    "\n[语义判断与回复决策]",
                    f"intent: {state.get('intent', '')}",
                    f"emotion: {state.get('emotion', '')}",
                    f"user_need: {state.get('user_need', '')}",
                    f"relationship_signal: {state.get('relationship_signal', '')}",
                    f"should_reply: {state.get('should_reply', '')}",
                    f"no_reply_reason: {state.get('no_reply_reason', '')}",
                    f"reply_strategy: {state.get('reply_strategy', '')}",
                    f"risk_flags: {json.dumps(state.get('risk_flags') or [], ensure_ascii=False)}",
                ]
            )
        return "\n".join(lines)

    def _prompt_extensions_text(self, state: WechatReplyState) -> str:
        extensions = state.get("prompt_extensions") or []
        if not isinstance(extensions, list):
            return ""
        parts: list[str] = []
        for item in extensions:
            if not isinstance(item, dict):
                continue
            name = sanitize_text(str(item.get("name") or "未命名扩展")).strip()
            weight = item.get("weight", 1.0)
            content = sanitize_text(str(item.get("content") or "")).strip()
            if content:
                parts.append(f"[{name} | 权重 {weight}]\n{content}")
        return "\n\n".join(parts)

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
            return [value] if value.strip() else []
        if isinstance(value, list):
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
                local = self._rewrite_locally([cleaned], state)
                cleaned = local[0] if local else ""
                rewrote = True
                safety_reasons.append("已本地移除 AI/客服腔表达")
            shortened = self._shorten(cleaned, max_chars)
            if shortened != cleaned:
                rewrote = True
                safety_reasons.append("已按回复策略缩短单条消息")
            if shortened:
                final_messages.append(shortened)
        if len(messages) > max_messages:
            rewrote = True
            safety_reasons.append("已按回复策略截断消息条数")
        if not final_messages:
            return {"safety_action": "skip", "safety_reasons": safety_reasons or ["安全检查后无可发送内容"], "final_messages": []}
        return {
            "safety_action": "rewrite" if rewrote else action,
            "safety_reasons": list(dict.fromkeys(safety_reasons)),
            "final_messages": final_messages,
        }

    def _max_messages(self, state: WechatReplyState) -> int:
        reply_settings = self._node_settings(state).get("reply_strategy") or {}
        config_limit = int(state.get("max_messages_per_turn") or 2)
        node_limit = int(reply_settings.get("default_max_messages") or config_limit)
        return max(1, min(config_limit, node_limit))

    def _max_chars_per_message(self, state: WechatReplyState) -> int:
        reply_settings = self._node_settings(state).get("reply_strategy") or {}
        return int(reply_settings.get("default_max_chars_per_message") or 80)

    def _shorten(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip(" ，,。")

    def _matched_avoid_topic(self, messages: list[str], state: WechatReplyState) -> str:
        return ""

    def _risk_flags(self, state: WechatReplyState, model_flags: list[str]) -> list[str]:
        text = "\n".join(
            [
                str(state.get("trigger_message", "")),
                "\n".join(self._coerce_message_list(state.get("recent_messages"))[-3:]),
                "\n".join(self._coerce_message_list(state.get("draft_messages"))),
            ]
        )
        flags = [flag for flag in model_flags if flag]
        risk_settings = self._node_settings(state).get("risk") or {}
        keywords = risk_settings.get("risk_keywords") if isinstance(risk_settings.get("risk_keywords"), list) else RISK_KEYWORDS
        for keyword in keywords:
            if keyword in text:
                flags.append(keyword)
        return list(dict.fromkeys(flags))

    def _policy_allows_proactive(self, state: WechatReplyState) -> bool:
        proactive_mode = str(state.get("proactive_mode") or "off").lower()
        if proactive_mode in {"", "off", "false", "0", "disabled"}:
            return False
        proactive_settings = self._node_settings(state).get("proactive") or {}
        if proactive_settings.get("enabled") is False:
            return False
        return True

    def _has_media_turn(self, state: WechatReplyState) -> bool:
        message_type = str(state.get("trigger_message_type", "")).lower()
        if message_type in {"image", "sticker", "voice", "file", "unsupported"}:
            return True
        text = str(state.get("trigger_message", ""))
        return any(marker in text for marker in MEDIA_MARKERS)

    def _media_text(self, state: WechatReplyState) -> str:
        chunks = [str(state.get("trigger_message", ""))]
        chunks.extend(self._coerce_message_list(state.get("recent_messages"))[-3:])
        return "\n".join(chunk for chunk in chunks if any(marker in chunk for marker in MEDIA_MARKERS))

    def _compact_json(self, value: dict[str, Any], keys: tuple[str, ...]) -> str:
        if not isinstance(value, dict):
            return "{}"
        compact = {key: value.get(key) for key in keys if value.get(key) not in (None, "", [], {})}
        return json.dumps(compact, ensure_ascii=False)

    def _node_settings(self, state: WechatReplyState) -> dict[str, Any]:
        settings = state.get("node_settings") or {}
        return settings if isinstance(settings, dict) else {}

    def _recent_messages(self, state: WechatReplyState) -> list[str]:
        semantic_settings = self._node_settings(state).get("semantic") or {}
        limit = int(semantic_settings.get("recent_message_limit") or 8)
        return self._coerce_message_list(state.get("recent_messages"))[-max(1, limit):]
