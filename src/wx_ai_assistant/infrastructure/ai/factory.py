from __future__ import annotations

from wx_ai_assistant.core.config import Settings
from wx_ai_assistant.infrastructure.ai.dummy_ai import DummyAiGateway, EchoAiGateway
from wx_ai_assistant.infrastructure.ai.openai_compatible_ai import OpenAICompatibleAiGateway, OpenAICompatibleConfig
from wx_ai_assistant.ports.ai_gateway import AiGateway


def build_ai_gateway(settings: Settings, force_mode: str | None = None) -> AiGateway:
    mode = (force_mode or settings.ai_mode).strip().lower()
    if mode == "echo":
        return EchoAiGateway()
    if mode in {"openai_compatible", "openai-compatible", "qwen", "dashscope"}:
        return OpenAICompatibleAiGateway(
            OpenAICompatibleConfig(
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                temperature=settings.ai_temperature,
                max_tokens=settings.ai_max_tokens,
                timeout_seconds=settings.ai_timeout_seconds,
                system_prompt=settings.ai_system_prompt,
                extra_body=settings.ai_extra_body,
            )
        )
    return DummyAiGateway()
