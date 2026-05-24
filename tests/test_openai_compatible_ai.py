import json

from wx_ai_assistant.domain.enums import MessageType, SenderType
from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.infrastructure.ai.openai_compatible_ai import OpenAICompatibleAiGateway, OpenAICompatibleConfig


def test_openai_compatible_extracts_chat_completion_text():
    gateway = OpenAICompatibleAiGateway(OpenAICompatibleConfig(base_url="https://example.com/v1", api_key="sk", model="m"))

    text = gateway._extract_reply_text({"choices": [{"message": {"content": "你好"}}]})

    assert text == "你好"


def test_openai_compatible_payload_includes_extra_body():
    gateway = OpenAICompatibleAiGateway(
        OpenAICompatibleConfig(
            base_url="https://example.com/v1",
            api_key="sk",
            model="deepseek-v4-flash",
            extra_body='{"enable_thinking": false}',
        )
    )
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "你好")

    payload = gateway._build_payload("上下文", msg)

    assert payload["model"] == "deepseek-v4-flash"
    assert payload["enable_thinking"] is False
    assert json.dumps(payload, ensure_ascii=False).find("上下文") > -1


def test_openai_compatible_missing_key_fails_before_network():
    gateway = OpenAICompatibleAiGateway(OpenAICompatibleConfig(base_url="https://example.com/v1", api_key="", model="m"))
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "你好")

    try:
        gateway.generate_reply("上下文", msg)
    except RuntimeError as exc:
        assert "APP_AI_API_KEY" in str(exc)
    else:
        raise AssertionError("missing key should fail")
