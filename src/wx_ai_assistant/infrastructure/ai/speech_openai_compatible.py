from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from wx_ai_assistant.core.text_sanitize import sanitize_text
from wx_ai_assistant.ports.speech_gateway import SpeechGateway


@dataclass(frozen=True)
class OpenAICompatibleSpeechConfig:
    base_url: str
    api_key: str
    model: str = "gpt-4o-mini-transcribe"
    language: str = "zh"
    prompt: str = "这是一条微信语音消息，请转写为简体中文。"
    timeout_seconds: float = 30
    response_format: str = "json"


class OpenAICompatibleSpeechGateway(SpeechGateway):
    """OpenAI-compatible speech-to-text gateway for voice-message transcription."""

    def __init__(self, config: OpenAICompatibleSpeechConfig):
        self.config = config

    def transcribe_audio(self, audio_path: str, prompt: str = "") -> str:
        if not self.config.api_key:
            raise RuntimeError("APP_SPEECH_AI_API_KEY 为空。请填写 config/ai.local.env 后重启服务。")
        path = Path(audio_path)
        if not path.exists():
            raise RuntimeError(f"语音文件不存在: {path}")
        data, content_type = self._multipart_payload(path, prompt)
        request = urllib.request.Request(
            self._transcriptions_url(),
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": content_type,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Speech AI HTTP {exc.code}: {error_body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Speech AI 请求失败: {exc}") from exc
        return self._extract_text(body).strip()

    def _multipart_payload(self, audio_path: Path, prompt: str) -> tuple[bytes, str]:
        boundary = f"----chatwe-speech-{uuid4().hex}"
        fields = {
            "model": self.config.model,
            "response_format": self.config.response_format,
        }
        if self.config.language:
            fields["language"] = self.config.language
        effective_prompt = sanitize_text(prompt or self.config.prompt).strip()
        if effective_prompt:
            fields["prompt"] = effective_prompt

        parts: list[bytes] = []
        for key, value in fields.items():
            parts.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        mime_type = mimetypes.guess_type(str(audio_path))[0] or "application/octet-stream"
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
                    f"Content-Type: {mime_type}\r\n\r\n"
                ).encode("utf-8"),
                audio_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode("ascii"),
            ]
        )
        return b"".join(parts), f"multipart/form-data; boundary={boundary}"

    def _transcriptions_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/audio/transcriptions"):
            return base
        return f"{base}/audio/transcriptions"

    def _extract_text(self, body: str) -> str:
        if self.config.response_format == "text":
            return sanitize_text(body)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return sanitize_text(body)
        text = data.get("text")
        if isinstance(text, str):
            return sanitize_text(text)
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return sanitize_text(output_text)
        raise RuntimeError("Speech AI 响应中没有转写文本")
