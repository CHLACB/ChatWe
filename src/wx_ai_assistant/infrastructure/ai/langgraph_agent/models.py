from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

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
