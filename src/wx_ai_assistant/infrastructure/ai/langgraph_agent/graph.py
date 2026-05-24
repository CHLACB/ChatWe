from __future__ import annotations

from typing import Literal

from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import JsonChatClient
from wx_ai_assistant.infrastructure.ai.langgraph_agent.nodes import WechatReplyNodes
from wx_ai_assistant.infrastructure.ai.langgraph_agent.state import WechatReplyState


def build_wechat_reply_graph(client: JsonChatClient, policy_loader=None):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("缺少 langgraph。请执行: pip install langgraph langchain langchain-openai") from exc

    nodes = WechatReplyNodes(client, policy_loader=policy_loader)
    graph = StateGraph(WechatReplyState)
    graph.add_node("load_contact_policy", nodes.load_contact_policy)
    graph.add_node("analyze_intent", nodes.analyze_intent)
    graph.add_node("decide_reply", nodes.decide_reply)
    graph.add_node("plan_response", nodes.plan_response)
    graph.add_node("draft_reply", nodes.draft_reply)
    graph.add_node("auto_safety_check", nodes.auto_safety_check)
    graph.add_node("format_output", nodes.format_output)

    graph.add_edge(START, "load_contact_policy")
    graph.add_edge("load_contact_policy", "analyze_intent")
    graph.add_edge("analyze_intent", "decide_reply")
    graph.add_conditional_edges(
        "decide_reply",
        _route_after_decide,
        {
            "reply": "plan_response",
            "skip": "format_output",
        },
    )
    graph.add_edge("plan_response", "draft_reply")
    graph.add_edge("draft_reply", "auto_safety_check")
    graph.add_edge("auto_safety_check", "format_output")
    graph.add_edge("format_output", END)
    return graph.compile()


def _route_after_decide(state: WechatReplyState) -> Literal["reply", "skip"]:
    return "reply" if state.get("should_reply", False) else "skip"
