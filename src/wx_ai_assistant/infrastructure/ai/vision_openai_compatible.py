from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wx_ai_assistant.core.text_sanitize import sanitize_jsonable
from wx_ai_assistant.domain.enums import MessageType
from wx_ai_assistant.ports.vision_gateway import VisionGateway


@dataclass(frozen=True)
class OpenAICompatibleVisionConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.1
    max_tokens: int = 300
    timeout_seconds: float = 30
    system_prompt: str = (
        "你是微信图片和表情包识别器。只描述图片/表情包里能看见的内容、文字和表达的情绪。"
        "不要生成聊天回复，不要自称 AI。"
    )
    extra_body: str = ""


class OpenAICompatibleVisionGateway(VisionGateway):
    """OpenAI-compatible vision gateway for image/sticker recognition."""

    def __init__(self, config: OpenAICompatibleVisionConfig):
        self.config = config

    def describe_image(self, image_path: str, message_type: MessageType, prompt: str = "") -> str:
        if not self.config.api_key:
            raise RuntimeError("APP_VISION_AI_API_KEY 为空。请填写 config/ai.local.env 后重启服务。")
        path = Path(image_path)
        if not path.exists():
            raise RuntimeError(f"图片文件不存在: {path}")
        payload = self._build_payload(path, message_type, prompt)
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
            raise RuntimeError(f"Vision AI HTTP {exc.code}: {error_body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Vision AI 请求失败: {exc}") from exc
        return self._extract_text(json.loads(body)).strip()

    def _build_payload(self, image_path: Path, message_type: MessageType, prompt: str) -> dict[str, Any]:
        media_label = "表情包" if message_type == MessageType.STICKER else "图片"
        task_prompt = prompt.strip() or (
            f"请识别这张微信{media_label}。输出一段简短中文描述，包含："
            "画面内容、图中文字、表情/情绪含义。不要超过80字。"
        )
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": task_prompt},
                        {"type": "image_url", "image_url": {"url": self._data_url(image_path)}},
                    ],
                },
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.extra_body:
            try:
                extra = json.loads(self.config.extra_body)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"APP_VISION_AI_EXTRA_BODY 不是合法 JSON: {exc}") from exc
            if not isinstance(extra, dict):
                raise RuntimeError("APP_VISION_AI_EXTRA_BODY 必须是 JSON object")
            payload.update(extra)
        return payload

    def _data_url(self, image_path: Path) -> str:
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _chat_completions_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _extract_text(self, data: dict[str, Any]) -> str:
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
        raise RuntimeError("Vision AI 响应中没有识别文本")
