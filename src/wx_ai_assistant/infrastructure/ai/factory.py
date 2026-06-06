from __future__ import annotations

from wx_ai_assistant.core.config import Settings
from wx_ai_assistant.infrastructure.ai.dummy_ai import DummyAiGateway, EchoAiGateway
from wx_ai_assistant.infrastructure.ai.langgraph_agent import LangGraphAiConfig, LangGraphAiGateway
from wx_ai_assistant.infrastructure.ai.openai_compatible_ai import OpenAICompatibleAiGateway, OpenAICompatibleConfig
from wx_ai_assistant.infrastructure.ai.prompt_library import compose_system_prompt
from wx_ai_assistant.ports.ai_gateway import AiGateway
from wx_ai_assistant.ports.repository import Repository


def build_ai_gateway(settings: Settings, force_mode: str | None = None, repository: Repository | None = None) -> AiGateway:
    mode = (force_mode or settings.ai_mode).strip().lower()
    if mode == "echo":
        return EchoAiGateway()
    if mode == "langgraph":
        return LangGraphAiGateway(
            LangGraphAiConfig(
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                temperature=settings.ai_temperature,
                max_tokens=settings.ai_max_tokens,
                timeout_seconds=settings.ai_timeout_seconds,
                extra_body=settings.ai_extra_body,
                proactive_mode=settings.ai_proactive_mode,
                max_messages_per_turn=settings.ai_max_messages_per_turn,
                node_settings_path=str(settings.langgraph_nodes_path),
                system_prompt_path=str(settings.ai_core_prompt_path),
                prompt_extensions_path=str(settings.ai_extensions_path),
            ),
            repository=repository,
        )
    if mode in {"openai_compatible", "openai-compatible", "qwen", "dashscope"}:
        return OpenAICompatibleAiGateway(
            OpenAICompatibleConfig(
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                temperature=settings.ai_temperature,
                max_tokens=settings.ai_max_tokens,
                timeout_seconds=settings.ai_timeout_seconds,
                system_prompt=compose_system_prompt(
                    settings.ai_core_prompt_path,
                    settings.ai_prompt_path,
                    settings.ai_style_path,
                    settings.ai_system_prompt,
                    settings.ai_proactive_mode,
                    settings.ai_extensions_path,
                ),
                extra_body=settings.ai_extra_body,
            )
        )
    return DummyAiGateway()
