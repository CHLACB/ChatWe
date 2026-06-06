import json

from wx_ai_assistant.domain.enums import MessageType, SenderType
from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.infrastructure.ai.openai_compatible_ai import OpenAICompatibleAiGateway, OpenAICompatibleConfig
from wx_ai_assistant.infrastructure.ai.speech_openai_compatible import OpenAICompatibleSpeechConfig, OpenAICompatibleSpeechGateway
from wx_ai_assistant.infrastructure.ai.vision_openai_compatible import OpenAICompatibleVisionConfig, OpenAICompatibleVisionGateway
from wx_ai_assistant.core.text_sanitize import sanitize_jsonable


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


def test_openai_compatible_sanitizes_unpaired_surrogates_before_json_encoding():
    gateway = OpenAICompatibleAiGateway(OpenAICompatibleConfig(base_url="https://example.com/v1", api_key="sk", model="m"))
    payload = {"messages": [{"content": "bad \ud83d"}]}

    sanitized = sanitize_jsonable(payload)

    assert sanitized["messages"][0]["content"] == "bad ?"
    json.dumps(sanitized, ensure_ascii=False).encode("utf-8")


def test_openai_compatible_vision_payload_uses_image_url_data_url(tmp_path):
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    gateway = OpenAICompatibleVisionGateway(
        OpenAICompatibleVisionConfig(
            base_url="http://example.test/v1",
            api_key="key",
            model="qwen-vl-plus",
        )
    )

    payload = gateway._build_payload(image, MessageType.IMAGE, "")

    assert payload["model"] == "qwen-vl-plus"
    content = payload["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_compatible_speech_payload_uses_audio_transcriptions_multipart(tmp_path):
    audio = tmp_path / "voice.m4a"
    audio.write_bytes(b"audio")
    gateway = OpenAICompatibleSpeechGateway(
        OpenAICompatibleSpeechConfig(
            base_url="http://example.test/v1",
            api_key="key",
            model="gpt-4o-mini-transcribe",
            language="zh",
        )
    )

    data, content_type = gateway._multipart_payload(audio, "")

    assert gateway._transcriptions_url() == "http://example.test/v1/audio/transcriptions"
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="model"' in data
    assert b"gpt-4o-mini-transcribe" in data
    assert b'name="language"' in data
    assert b"zh" in data
    assert b'name="file"; filename="voice.m4a"' in data
