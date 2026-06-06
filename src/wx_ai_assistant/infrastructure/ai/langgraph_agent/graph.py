from __future__ import annotations

from typing import Literal

from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import JsonChatClient
from wx_ai_assistant.infrastructure.ai.langgraph_agent.nodes import WechatReplyNodes
from wx_ai_assistant.infrastructure.ai.langgraph_agent.state import WechatReplyState


def build_wechat_reply_graph(client: JsonChatClient, node_settings_loader=None):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("缺少 langgraph。请执行: pip install langgraph langchain langchain-openai") from exc

    nodes = WechatReplyNodes(
        client,
        node_settings_loader=node_settings_loader,
    )
    graph = StateGraph(WechatReplyState)
    graph.add_node("load_node_settings", nodes.load_node_settings)
    graph.add_node("retrieve_memory_context", nodes.retrieve_memory_context)
    graph.add_node("media_understanding", nodes.media_understanding)
    graph.add_node("semantic_reply_decision", nodes.semantic_reply_decision)
    graph.add_node("draft_reply", nodes.draft_reply)
    graph.add_node("rule_safety_check", nodes.rule_safety_check)
    graph.add_node("model_safety_check", nodes.model_safety_check)
    graph.add_node("format_output", nodes.format_output)

    graph.add_edge(START, "load_node_settings")
    graph.add_edge("load_node_settings", "retrieve_memory_context")
    graph.add_conditional_edges(
        "retrieve_memory_context",
        _route_after_profile,
        {
            "media": "media_understanding",
            "semantic": "semantic_reply_decision",
        },
    )
    graph.add_edge("media_understanding", "semantic_reply_decision")
    graph.add_conditional_edges(
        "semantic_reply_decision",
        _route_after_decide,
        {
            "reply": "draft_reply",
            "skip": "format_output",
        },
    )
    graph.add_edge("draft_reply", "rule_safety_check")
    graph.add_conditional_edges(
        "rule_safety_check",
        _route_after_rule_safety,
        {
            "model": "model_safety_check",
            "format": "format_output",
        },
    )
    graph.add_edge("model_safety_check", "format_output")
    graph.add_edge("format_output", END)
    return graph.compile()


def _route_after_profile(state: WechatReplyState) -> Literal["media", "semantic"]:
    message_type = str(state.get("trigger_message_type", "")).lower()
    text = str(state.get("trigger_message", ""))
    if message_type in {"image", "sticker", "voice", "file", "unsupported"}:
        return "media"
    if any(marker in text for marker in ("[图片", "[表情", "[语音", "[文件", "图片识别", "表情包识别", "语音转写")):
        return "media"
    return "semantic"


def _route_after_decide(state: WechatReplyState) -> Literal["reply", "skip"]:
    return "reply" if state.get("should_reply", False) else "skip"


def _route_after_rule_safety(state: WechatReplyState) -> Literal["model", "format"]:
    return "model" if state.get("requires_safety_model", False) else "format"
