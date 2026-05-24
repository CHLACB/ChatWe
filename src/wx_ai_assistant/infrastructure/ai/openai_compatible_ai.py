from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.ports.ai_gateway import AiGateway


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 800
    timeout_seconds: float = 30
    system_prompt: str = "你是一个微信私聊助手。请只输出最终要发送给对方的文本。"
    extra_body: str = ""


class OpenAICompatibleAiGateway(AiGateway):
    """OpenAI-compatible chat completions gateway.

    This keeps model access behind the AiGateway port. It can be used with
    Alibaba Cloud Model Studio/DashScope compatible mode or any endpoint that
    implements /chat/completions.
    """

    def __init__(self, config: OpenAICompatibleConfig):
        self.config = config

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        if not self.config.api_key:
            raise RuntimeError("APP_AI_API_KEY 为空。请填写 config/ai.local.env 后重启服务。")
        payload = self._build_payload(context, trigger_message)
        request = urllib.request.Request(
            self._chat_completions_url(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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
            raise RuntimeError(f"AI 网关 HTTP {exc.code}: {error_body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AI 网关请求失败: {exc}") from exc

        return self._extract_reply_text(json.loads(body)).strip()

    def _build_payload(self, context: str, trigger_message: Message) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {
                    "role": "user",
                    "content": (
                        "下面是微信私聊上下文。请根据当前触发消息生成本轮回复。\n"
                        "必须输出 JSON object，格式为 {\"messages\":[\"...\"],\"done\":true}。\n"
                        "messages 中每个元素就是一条微信消息；不要让程序再拆分你的句子。\n"
                        "本轮回复完成后 done 必须为 true，表示停在这里等待对方下一条消息。\n\n"
                        f"{context}\n\n"
                        f"触发消息: {trigger_message.content}"
                    ),
                },
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
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
                return content
            if isinstance(content, list):
                parts = [part.get("text", "") for part in content if isinstance(part, dict)]
                return "".join(parts)
            text = choices[0].get("text")
            if isinstance(text, str):
                return text
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text
        raise RuntimeError("AI 网关响应中没有可发送文本")
