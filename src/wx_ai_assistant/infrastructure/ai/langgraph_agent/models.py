from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from wx_ai_assistant.core.text_sanitize import sanitize_jsonable, sanitize_text


@dataclass(frozen=True)
class LangGraphAiConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 800
    timeout_seconds: float = 30
    extra_body: str = ""
    proactive_mode: str = "off"
    max_messages_per_turn: int = 2
    node_settings_path: str = "./config/langgraph_nodes.local.json"
    system_prompt_path: str = "./config/prompts/system.core.md"
    prompt_extensions_path: str = "./config/prompts/extensions.local.json"


class ProactiveStrategy(BaseModel):
    enabled: bool = False
    mode: str = "off"
    level: str = "controlled"
    cooldown_minutes: int = 240
    max_messages_per_day: int = 1
    allowed_windows: list[str] = Field(default_factory=lambda: ["10:00-22:30"])
    quiet_hours: list[str] = Field(default_factory=lambda: ["23:30-09:00"])
    requires_recent_context: bool = True
    topic_policy: str = "关闭主动触达。没有对方新消息时不主动开新话题。"


class ContactPolicy(BaseModel):
    name: str = "default"
    proactive_mode: str = "off"
    max_messages_per_turn: int = 2
    tone: str = "natural_short"
    allow_questions: bool = True
    community_context: dict[str, Any] = Field(default_factory=dict)
    relationship_strategy: dict[str, Any] = Field(default_factory=dict)
    proactive_strategy: ProactiveStrategy = Field(default_factory=ProactiveStrategy)
    notes: str = ""


class ConversationProfile(BaseModel):
    relationship: str = "普通微信联系人"
    background: str = ""
    communication_style: str = "自然、简短、不过度热情"
    initiative_level: str = "low"
    max_messages: int = 1
    max_chars_per_message: int = 60
    allow_follow_up_question: bool = True
    allow_emotional_support: bool = True
    community_awareness: dict[str, Any] = Field(default_factory=dict)
    known_preferences: list[str] = Field(default_factory=list)
    manual_memories: list[str] = Field(default_factory=list)
    avoid_topics: list[str] = Field(default_factory=list)
    hard_rules: list[str] = Field(
        default_factory=lambda: [
            "不要暴露自己是 AI",
            "不要自称机器人",
            "不要主动承诺现实中无法完成的事情",
            "不要连续追问",
            "不确定时回复简短确认或请求对方补充",
        ]
    )


class MemoryRetrievalSettings(BaseModel):
    enabled: bool = True
    top_k: int = 3
    max_chars: int = 240


class SemanticNodeSettings(BaseModel):
    recent_message_limit: int = 8
    context_summary_max_chars: int = 500
    confidence_threshold: float = 0.55
    detect_community_context: bool = False
    community_signal_policy: str = ""


class ReplyStrategyNodeSettings(BaseModel):
    default_max_messages: int = 1
    default_max_chars_per_message: int = 60
    allow_follow_up_question: bool = True
    question_policy: str = "可轻问一句"
    initiative_level: str = "low"
    ending_style: str = "停住等对方"
    community_reply_policy: str = ""


class StyleControlSettings(BaseModel):
    persona: str = "female_flirty_reserved"
    variability: str = "medium_high"
    push_pull_enabled: bool = True
    soft_teasing_enabled: bool = True
    soft_suppression_enabled: bool = True
    clingy_level: str = "low"
    sweetness_level: str = "medium"
    logic_strictness: str = "low_medium"
    emotional_variation: str = "medium_high"
    avoid_fixed_pattern: bool = True
    frame_control: str = "medium"
    community_tone: str = ""


class ProactiveNodeSettings(BaseModel):
    enabled: bool = True
    default_mode: str = "off"
    manual_trigger_only: bool = True
    min_recent_messages: int = 1
    cooldown_minutes: int = 240
    max_messages_per_day: int = 1
    risk_stop_keywords: list[str] = Field(
        default_factory=lambda: ["钱", "转账", "借钱", "密码", "验证码", "身份证", "银行卡", "隐私照", "见面", "酒店", "开房"]
    )
    decision_policy: str = "只有全局主动模式开启时才允许主动；每次只生成 0 或 1 条，必须短、轻、可退。"


class MediaNodeSettings(BaseModel):
    enabled: bool = True
    max_observations: int = 3


class RiskNodeSettings(BaseModel):
    rule_first: bool = True
    model_check_only_when_risky: bool = True
    risk_keywords: list[str] = Field(
        default_factory=lambda: [
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
        ]
    )
    community_risk_policy: str = ""


class LangGraphNodeSettings(BaseModel):
    memory_retrieval: MemoryRetrievalSettings = Field(default_factory=MemoryRetrievalSettings)
    semantic: SemanticNodeSettings = Field(default_factory=SemanticNodeSettings)
    reply_strategy: ReplyStrategyNodeSettings = Field(default_factory=ReplyStrategyNodeSettings)
    style_control: StyleControlSettings = Field(default_factory=StyleControlSettings)
    proactive: ProactiveNodeSettings = Field(default_factory=ProactiveNodeSettings)
    media_understanding: MediaNodeSettings = Field(default_factory=MediaNodeSettings)
    risk: RiskNodeSettings = Field(default_factory=RiskNodeSettings)


class SemanticReplyDecisionOutput(BaseModel):
    intent: str = ""
    emotion: str = ""
    user_need: str = ""
    relationship_signal: str = ""
    should_reply: bool = False
    no_reply_reason: str = ""
    reply_strategy: str = ""
    risk_flags: list[str] = Field(default_factory=list)


class ProactiveSendDecisionOutput(BaseModel):
    should_send: bool = False
    no_send_reason: str = ""
    suggested_message: str = ""
    strategy: str = ""
    risk_flags: list[str] = Field(default_factory=list)


class MediaUnderstandingOutput(BaseModel):
    media_observations: list[str] = Field(default_factory=list)


class DraftReplyOutput(BaseModel):
    draft_messages: list[str] = Field(default_factory=list)


class SafetyCheckOutput(BaseModel):
    safety_action: str = "allow"
    safety_reasons: list[str] = Field(default_factory=list)
    rewritten_messages: list[str] = Field(default_factory=list)


class JsonChatClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...


class OpenAICompatibleJsonClient:
    def __init__(self, config: LangGraphAiConfig):
        self.config = config

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        text = self.complete_text(system_prompt, user_prompt)
        data = self._extract_json_object(text)
        if not isinstance(data, dict):
            raise RuntimeError(f"AI 节点未返回 JSON object: {text[:300]}")
        return data

    def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        if not self.config.api_key:
            raise RuntimeError("APP_AI_API_KEY 为空。请填写 config/ai.local.env 后重启服务。")
        payload = self._build_payload(system_prompt, user_prompt)
        request = urllib.request.Request(
            self._chat_completions_url(),
            data=json.dumps(sanitize_jsonable(payload), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LangGraph AI 节点 HTTP {exc.code}: {error_body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LangGraph AI 节点请求失败: {exc}") from exc
        return self._extract_reply_text(json.loads(body)).strip()

    def _build_payload(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self.config.extra_body:
            try:
                extra = json.loads(self.config.extra_body)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"APP_AI_EXTRA_BODY 不是合法 JSON: {exc}") from exc
            if not isinstance(extra, dict):
                raise RuntimeError("APP_AI_EXTRA_BODY 必须是 JSON object")
            payload.update(extra)
        return payload

    def _chat_completions_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _extract_reply_text(self, data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return sanitize_text(content)
            if isinstance(content, list):
                parts = [part.get("text", "") for part in content if isinstance(part, dict)]
                return sanitize_text("".join(parts))
            text = choices[0].get("text")
            if isinstance(text, str):
                return sanitize_text(text)
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return sanitize_text(output_text)
        raise RuntimeError("AI 网关响应中没有可解析文本")

    def _extract_json_object(self, text: str) -> Any:
        sanitized = sanitize_text(text).strip()
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError:
            pass
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", sanitized, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass
        start = sanitized.find("{")
        end = sanitized.rfind("}")
        if start >= 0 and end > start:
            return json.loads(sanitized[start : end + 1])
        return None
