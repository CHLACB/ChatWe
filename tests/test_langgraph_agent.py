import json

import pytest

from wx_ai_assistant.core.config import Settings
from wx_ai_assistant.domain.enums import MessageType, SenderType
from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.infrastructure.ai.factory import build_ai_gateway
from wx_ai_assistant.infrastructure.ai.langgraph_agent.gateway import LangGraphAiConfig, LangGraphAiGateway
from wx_ai_assistant.infrastructure.ai.langgraph_agent.graph import build_wechat_reply_graph
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import JsonChatClient


class ScriptedJsonClient(JsonChatClient):
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete_json(self, system_prompt: str, user_prompt: str):
        self.prompts.append((system_prompt, user_prompt))
        if not self.replies:
            raise AssertionError("no scripted reply left")
        return self.replies.pop(0)


def test_langgraph_gateway_replies_to_plain_question():
    client = ScriptedJsonClient(
        [
            {"intent": "问是否有空", "emotion": "中性", "user_need": "希望得到回应", "relationship_signal": "普通私聊"},
            {"should_reply": True, "no_reply_reason": ""},
            {"reply_strategy": "简短确认"},
            {"draft_messages": ["有空，你说"]},
            {"safety_action": "allow", "safety_reasons": [], "rewritten_messages": []},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "你现在有空吗", sender_name="AAxc")

    raw = gateway.generate_reply("recent context", msg)

    assert json.loads(raw) == {"messages": ["有空，你说"], "done": True}


def test_langgraph_gateway_can_decide_no_reply():
    client = ScriptedJsonClient(
        [
            {"intent": "普通笑声", "emotion": "开心", "user_need": "无明确需求", "relationship_signal": "轻松"},
            {"should_reply": False, "no_reply_reason": "只是笑声，不需要继续补充"},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "哈哈", sender_name="AAxc")

    raw = gateway.generate_reply("recent context", msg)

    assert json.loads(raw) == {"messages": [], "done": True}


def test_langgraph_safety_rewrites_identity_claim_before_send():
    client = ScriptedJsonClient(
        [
            {"intent": "追问身份", "emotion": "中性", "user_need": "确认身份", "relationship_signal": "普通私聊"},
            {"should_reply": True, "no_reply_reason": ""},
            {"reply_strategy": "自然带过，不承认身份"},
            {"draft_messages": ["我是AI助手，你有事可以跟我说"]},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "你是不是ai", sender_name="AAxc")

    raw = gateway.generate_reply("recent context", msg)

    messages = json.loads(raw)["messages"]
    assert messages
    assert "AI" not in messages[0]
    assert "助手" not in messages[0]


def test_factory_builds_langgraph_gateway(monkeypatch, tmp_path):
    try:
        import langgraph  # noqa: F401
    except ImportError:
        pytest.skip("langgraph is not installed")

    settings = Settings(
        driver_mode="mock",
        db_path=tmp_path / "app.sqlite3",
        poll_interval_seconds=1.0,
        ai_mode="langgraph",
        ai_config=tmp_path / "ai.env",
        ai_base_url="https://example.com/v1",
        ai_api_key="sk",
        ai_model="model",
        ai_temperature=0.3,
        ai_max_tokens=800,
        ai_timeout_seconds=30,
        ai_system_prompt="fallback",
        ai_core_prompt_path=tmp_path / "core.md",
        ai_prompt_path=tmp_path / "turn.md",
        ai_style_path=tmp_path / "style.md",
        ai_proactive_mode="off",
        ai_max_messages_per_turn=2,
        ai_strict_turn_json=True,
        ai_turn_quiet_seconds=5.0,
        ai_duplicate_guard_seconds=120.0,
        diagnostics_context_chars=1200,
        ai_extra_body="",
        history_mode="normalized_sqlite",
        history_db_path=tmp_path / "history.sqlite3",
        wechat_locators=tmp_path / "locators.json",
    )

    gateway = build_ai_gateway(settings)

    assert isinstance(gateway, LangGraphAiGateway)


def _config():
    return LangGraphAiConfig(
        base_url="https://example.com/v1",
        api_key="sk",
        model="model",
        max_messages_per_turn=2,
    )
