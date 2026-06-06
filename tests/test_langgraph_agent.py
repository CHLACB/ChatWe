import json

import pytest

from wx_ai_assistant.core.config import Settings
from wx_ai_assistant.domain.enums import MessageType, SenderType
from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.infrastructure.ai.factory import build_ai_gateway
from wx_ai_assistant.infrastructure.ai.langgraph_agent.contact_policy import ContactPolicyLoader
from wx_ai_assistant.infrastructure.ai.langgraph_agent.conversation_profile import ConversationProfileLoader
from wx_ai_assistant.infrastructure.ai.langgraph_agent.gateway import LangGraphAiConfig, LangGraphAiGateway
from wx_ai_assistant.infrastructure.ai.langgraph_agent.graph import build_wechat_reply_graph
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import JsonChatClient
from wx_ai_assistant.infrastructure.ai.langgraph_agent.node_settings import LangGraphNodeSettingsLoader


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
            {
                "intent": "问是否有空",
                "emotion": "中性",
                "user_need": "希望得到回应",
                "relationship_signal": "普通私聊",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "简短确认",
                "risk_flags": [],
            },
            {"draft_messages": ["有空，你说"]},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "你现在有空吗", sender_name="AAxc")

    raw = gateway.generate_reply("recent context", msg)

    assert json.loads(raw) == {"messages": ["有空，你说"], "done": True}
    assert len(client.prompts) == 2
    assert "一次完成语义判断和回复决策" in client.prompts[0][0]
    assert "自动安全检查" not in "\n".join(system for system, _ in client.prompts)


def test_langgraph_gateway_can_decide_no_reply():
    client = ScriptedJsonClient(
        [
            {
                "intent": "普通笑声",
                "emotion": "开心",
                "user_need": "无明确需求",
                "relationship_signal": "轻松",
                "should_reply": False,
                "no_reply_reason": "只是笑声，不需要继续补充",
                "reply_strategy": "",
                "risk_flags": [],
            },
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
            {
                "intent": "追问身份",
                "emotion": "中性",
                "user_need": "确认身份",
                "relationship_signal": "普通私聊",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "自然带过，不承认身份",
                "risk_flags": [],
            },
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


def test_contact_policy_loads_proactive_strategy(tmp_path):
    path = tmp_path / "policies.json"
    path.write_text(
        json.dumps(
            {
                "contacts": [
                    {
                        "display_name": "AAxc",
                        "policy": {
                            "proactive_mode": "light",
                            "proactive_strategy": {"enabled": True, "mode": "light"},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loader = ContactPolicyLoader(path)

    policy = loader.load_for_identity(None, "AAxc")

    assert policy.proactive_mode == "light"
    assert policy.proactive_strategy.enabled is True


def test_proactive_gateway_respects_global_proactive_off(tmp_path):
    client = ScriptedJsonClient([])
    gateway = LangGraphAiGateway(_config(proactive_mode="off"), client=client)
    from wx_ai_assistant.domain.enums import ConversationType
    from wx_ai_assistant.domain.models import ConversationIdentity

    identity = ConversationIdentity("conv", ConversationType.FRIEND, "AAxc")
    raw = gateway.generate_proactive_reply("recent context", identity, "轻轻问一下")

    assert json.loads(raw) == {"messages": [], "done": True}
    assert client.prompts == []


def test_proactive_gateway_generates_one_controlled_message(tmp_path):
    client = ScriptedJsonClient(
        [
            {
                "should_send": True,
                "no_send_reason": "",
                "suggested_message": "你这人怎么突然安静了",
                "strategy": "轻轻试探",
                "risk_flags": [],
            }
        ]
    )
    gateway = LangGraphAiGateway(_config(proactive_mode="on"), client=client)
    from wx_ai_assistant.domain.enums import ConversationType
    from wx_ai_assistant.domain.models import ConversationIdentity

    identity = ConversationIdentity("conv", ConversationType.FRIEND, "AAxc")
    raw = gateway.generate_proactive_reply("当前会话: AAxc\n[最近实时消息]\nother:AAxc: 晚点说", identity, "轻轻问一下")

    assert json.loads(raw) == {"messages": ["你这人怎么突然安静了"], "done": True}
    assert "主动触达判断" in client.prompts[0][0]


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
        ai_extensions_path=tmp_path / "extensions.json",
        ai_proactive_mode="off",
        ai_max_messages_per_turn=2,
        ai_strict_turn_json=True,
        ai_turn_quiet_seconds=5.0,
        ai_duplicate_guard_seconds=120.0,
        diagnostics_context_chars=1200,
        ai_extra_body="",
        auto_send_enabled=False,
        embedding_base_url="https://example.com/embeddings",
        embedding_api_key="sk",
        embedding_model="embedding-model",
        embedding_dimensions=768,
        embedding_timeout_seconds=30,
        langgraph_nodes_path=tmp_path / "langgraph_nodes.json",
        history_mode="normalized_sqlite",
        history_db_path=tmp_path / "history.sqlite3",
        wechat_locators=tmp_path / "locators.json",
    )

    gateway = build_ai_gateway(settings)

    assert isinstance(gateway, LangGraphAiGateway)


def test_contact_policy_missing_file_uses_default(tmp_path):
    loader = ContactPolicyLoader(tmp_path / "missing.json")

    policy = loader.load_for_identity(None, "AAxc")

    assert policy.name == "default"
    assert policy.proactive_mode == "off"


def test_contact_policy_matches_custom_display_name(tmp_path):
    path = tmp_path / "policies.json"
    path.write_text(
        json.dumps(
            {
                "default": {"max_messages_per_turn": 1},
                "contacts": [
                    {
                        "display_name": "AAxc",
                        "policy": {"name": "aaxc_policy", "max_messages_per_turn": 2, "tone": "casual"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loader = ContactPolicyLoader(path)

    policy = loader.load_for_identity(None, "AAxc")

    assert policy.name == "aaxc_policy"
    assert policy.max_messages_per_turn == 2


def test_conversation_profile_missing_file_uses_default(tmp_path):
    loader = ConversationProfileLoader(tmp_path / "missing.json")

    profile = loader.load_for_identity(None, "AAxc")

    assert profile.relationship == "普通微信联系人"
    assert profile.max_messages == 1


def test_conversation_profile_matches_custom_display_name(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "default": {"max_messages": 1},
                "AAxc": {
                    "relationship": "熟人",
                    "communication_style": "口语短句",
                    "initiative_level": "medium",
                    "max_messages": 2,
                    "max_chars_per_message": 30,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loader = ConversationProfileLoader(path)

    profile = loader.load_for_identity(None, "AAxc")

    assert profile.relationship == "熟人"
    assert profile.max_messages == 2


def test_node_settings_missing_file_uses_default(tmp_path):
    loader = LangGraphNodeSettingsLoader(tmp_path / "missing_nodes.json")

    settings = loader.load()

    assert settings.semantic.recent_message_limit == 8
    assert settings.reply_strategy.default_max_messages == 1


def test_node_settings_custom_recent_message_limit_controls_prompt(tmp_path):
    nodes_path = tmp_path / "nodes.json"
    nodes_path.write_text(
        json.dumps({"semantic": {"recent_message_limit": 3}}, ensure_ascii=False),
        encoding="utf-8",
    )
    loader = LangGraphNodeSettingsLoader(nodes_path)
    client = ScriptedJsonClient(
        [
            {
                "intent": "问候",
                "emotion": "中性",
                "user_need": "回应",
                "relationship_signal": "普通",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "短句",
                "risk_flags": [],
            },
            {"draft_messages": ["嗯"]},
        ]
    )
    graph = build_wechat_reply_graph(client, node_settings_loader=loader)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph, node_settings_loader=loader)
    recent_lines = "\n".join(f"other:friend: 新消息{i}" for i in range(6))
    context = f"[最近实时消息]\n{recent_lines}\n[当前触发消息]\n新消息5"
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "新消息5", sender_name="AAxc")

    gateway.generate_reply(context, msg)

    user_prompt = client.prompts[0][1]
    assert "新消息2" not in user_prompt
    assert "新消息3" in user_prompt
    assert "新消息5" in user_prompt


def test_system_and_extension_prompts_are_in_prompt(tmp_path):
    system_path = tmp_path / "system.md"
    system_path.write_text("男性主导，但保持自然短句。", encoding="utf-8")
    extensions_path = tmp_path / "extensions.json"
    extensions_path.write_text(
        json.dumps(
            {
                "extensions": [
                    {
                        "id": "relationship_progression",
                        "name": "关系推进",
                        "enabled": True,
                        "weight": 1.4,
                        "content": "正向回应时轻微升温或抛可退邀约钩子",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = ScriptedJsonClient(
        [
            {
                "intent": "暧昧回应",
                "emotion": "轻松",
                "user_need": "继续互动",
                "relationship_signal": "正向",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "轻微升温",
                "risk_flags": [],
            },
            {"draft_messages": ["那你表现好点呀"]},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(
        _config(system_prompt_path=str(system_path), prompt_extensions_path=str(extensions_path)),
        client=client,
        graph=graph,
    )

    gateway.generate_reply("[最近实时消息]\nother:friend: 那下次一起啊", Message("conv", SenderType.OTHER, MessageType.TEXT, "那下次一起啊", sender_name="AAxc"))

    user_prompt = client.prompts[0][1]
    assert "系统提示词" in user_prompt
    assert "男性主导，但保持自然短句。" in user_prompt
    assert "独立扩展提示词" in user_prompt
    assert "关系推进 | 权重 1.4" in user_prompt
    assert "正向回应时轻微升温或抛可退邀约钩子" in user_prompt


def test_conversation_profile_file_is_not_used_by_gateway(tmp_path):
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "AAxc": {
                    "relationship": "熟人",
                    "background": "一起调试微信自动回复项目",
                    "known_preferences": ["喜欢短句"],
                    "manual_memories": ["上次说过晚上再测试"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = ScriptedJsonClient(
        [
            {
                "intent": "继续测试",
                "emotion": "中性",
                "user_need": "回应",
                "relationship_signal": "熟人",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "短句",
                "risk_flags": [],
            },
            {"draft_messages": ["嗯，继续"]},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "继续测一下", sender_name="AAxc")

    gateway.generate_reply("ctx", msg)

    assert gateway.last_decision_snapshot["conversation_profile"] == {}
    assert gateway.last_decision_snapshot["retrieved_memories"] == []
    assert "调试微信自动回复项目" not in client.prompts[0][1]


def test_langgraph_safety_skip_returns_empty_final_messages():
    client = ScriptedJsonClient(
        [
            {
                "intent": "高风险请求",
                "emotion": "着急",
                "user_need": "要求承诺",
                "relationship_signal": "压力",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "不承诺",
                "risk_flags": ["转账"],
            },
            {"draft_messages": ["我给你转钱"]},
            {"safety_action": "skip", "safety_reasons": ["涉及转账"], "rewritten_messages": []},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "你先给我转钱", sender_name="AAxc")

    raw = gateway.generate_reply("recent context", msg)

    assert json.loads(raw) == {"messages": [], "done": True}
    assert len(client.prompts) == 3
    assert "风险场景" in client.prompts[-1][0]


def test_media_understanding_only_runs_for_media_message():
    client = ScriptedJsonClient(
        [
            {"media_observations": ["表情包表达开心和调侃"]},
            {
                "intent": "发来表情调侃",
                "emotion": "开心",
                "user_need": "轻松互动",
                "relationship_signal": "熟悉",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "短句接一下，不展开",
                "risk_flags": [],
            },
            {"draft_messages": ["哈哈哈"]},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.STICKER, "[表情包识别] 一张开心表情", sender_name="AAxc")

    raw = gateway.generate_reply("recent context", msg)

    assert json.loads(raw)["messages"] == ["哈哈哈"]
    assert len(client.prompts) == 3
    assert "整理已经识别出的媒体信息" in client.prompts[0][0]


def test_langgraph_prompt_uses_bounded_recent_message_window():
    client = ScriptedJsonClient(
        [
            {
                "intent": "问候",
                "emotion": "中性",
                "user_need": "回应",
                "relationship_signal": "普通",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "短句",
                "risk_flags": [],
            },
            {"draft_messages": ["嗯"]},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    old_lines = "\n".join(f"other:friend: 旧消息{i}" for i in range(20))
    recent_lines = "\n".join(f"other:friend: 新消息{i}" for i in range(10))
    context = f"当前会话: A2 (friend)\n[历史消息摘要输入]\n{old_lines}\n[最近实时消息]\n{recent_lines}\n[当前触发消息]\n新消息9"
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "新消息9", sender_name="AAxc")

    gateway.generate_reply(context, msg)

    user_prompt = client.prompts[0][1]
    assert "旧消息0" not in user_prompt
    assert "新消息0" not in user_prompt
    assert "新消息2" in user_prompt
    assert "新消息9" in user_prompt


def test_graph_does_not_load_conversation_profile_node(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"AAxc": {"relationship": "熟人"}}, ensure_ascii=False), encoding="utf-8")
    client = ScriptedJsonClient(
        [
            {
                "intent": "问候",
                "emotion": "中性",
                "user_need": "回应",
                "relationship_signal": "熟人",
                "should_reply": False,
                "no_reply_reason": "不需要",
                "reply_strategy": "",
                "risk_flags": [],
            },
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "hi", sender_name="AAxc")

    gateway.generate_reply("ctx", msg)

    assert gateway.last_decision_snapshot["conversation_profile"] == {}
    assert "会话画像摘要" not in client.prompts[0][1]


def test_safety_check_limits_max_messages_by_node_settings(tmp_path):
    node_settings = tmp_path / "nodes.json"
    node_settings.write_text(json.dumps({"reply_strategy": {"default_max_messages": 1}}, ensure_ascii=False), encoding="utf-8")
    client = ScriptedJsonClient(
        [
            {
                "intent": "问候",
                "emotion": "中性",
                "user_need": "回应",
                "relationship_signal": "普通",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "短句",
                "risk_flags": [],
            },
            {"draft_messages": ["第一句", "第二句"]},
        ]
    )
    gateway = LangGraphAiGateway(_config(node_settings_path=str(node_settings), max_messages_per_turn=3), client=client)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "hi", sender_name="AAxc")

    raw = gateway.generate_reply("ctx", msg)

    assert json.loads(raw)["messages"] == ["第一句"]


def test_safety_check_shortens_by_node_settings_chars(tmp_path):
    node_settings = tmp_path / "nodes.json"
    node_settings.write_text(
        json.dumps({"reply_strategy": {"default_max_chars_per_message": 5}}, ensure_ascii=False),
        encoding="utf-8",
    )
    client = ScriptedJsonClient(
        [
            {
                "intent": "问候",
                "emotion": "中性",
                "user_need": "回应",
                "relationship_signal": "普通",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "短句",
                "risk_flags": [],
            },
            {"draft_messages": ["这是一段很长的话"]},
        ]
    )
    gateway = LangGraphAiGateway(_config(node_settings_path=str(node_settings)), client=client)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "hi", sender_name="AAxc")

    raw = gateway.generate_reply("ctx", msg)

    assert json.loads(raw)["messages"] == ["这是一段很"]


def test_safety_check_uses_model_for_risky_topics_without_profile_avoid_list(tmp_path):
    client = ScriptedJsonClient(
        [
            {
                "intent": "钱款",
                "emotion": "中性",
                "user_need": "转账",
                "relationship_signal": "普通",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "跳过",
                "risk_flags": ["转账"],
            },
            {"draft_messages": ["我给你转账"]},
            {"safety_action": "skip", "safety_reasons": ["涉及转账"], "rewritten_messages": []},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "转账", sender_name="AAxc")

    raw = gateway.generate_reply("ctx", msg)

    assert json.loads(raw)["messages"] == []
    assert len(client.prompts) == 3


class CapturingRepository:
    def __init__(self):
        self.logs = []

    def save_ai_decision_log(self, log):
        self.logs.append(log)


def test_langgraph_gateway_saves_ai_decision_log():
    repo = CapturingRepository()
    client = ScriptedJsonClient(
        [
            {
                "intent": "问是否有空",
                "emotion": "中性",
                "user_need": "希望得到回应",
                "relationship_signal": "普通私聊",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "简短确认",
                "risk_flags": [],
            },
            {"draft_messages": ["有空，你说"]},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph, repository=repo)
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "你现在有空吗", sender_name="AAxc")

    raw = gateway.generate_reply("recent context", msg)

    assert json.loads(raw)["messages"] == ["有空，你说"]
    assert len(repo.logs) == 1
    assert repo.logs[0].run_id.startswith("lg_")
    assert repo.logs[0].intent == "问是否有空"
    assert isinstance(repo.logs[0].conversation_profile, dict)


class FailingRepository:
    def save_ai_decision_log(self, log):
        raise RuntimeError("db locked")


def test_langgraph_log_save_failure_does_not_block_reply():
    client = ScriptedJsonClient(
        [
            {
                "intent": "问是否有空",
                "emotion": "中性",
                "user_need": "希望得到回应",
                "relationship_signal": "普通私聊",
                "should_reply": True,
                "no_reply_reason": "",
                "reply_strategy": "简短确认",
                "risk_flags": [],
            },
            {"draft_messages": ["有空，你说"]},
        ]
    )
    graph = build_wechat_reply_graph(client)
    gateway = LangGraphAiGateway(_config(), client=client, graph=graph, repository=FailingRepository())
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, "你现在有空吗", sender_name="AAxc")

    raw = gateway.generate_reply("recent context", msg)

    assert json.loads(raw)["messages"] == ["有空，你说"]


def _config(**overrides):
    data = {
        "base_url": "https://example.com/v1",
        "api_key": "sk",
        "model": "model",
        "max_messages_per_turn": 2,
    }
    data.update(overrides)
    return LangGraphAiConfig(
        **data,
    )
