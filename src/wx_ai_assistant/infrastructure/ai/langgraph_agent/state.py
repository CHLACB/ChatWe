from __future__ import annotations

from typing import TypedDict
from typing import Any


class WechatReplyState(TypedDict, total=False):
    run_id: str
    context: str
    context_summary: str
    recent_messages: list[str]
    trigger_message_id: str
    trigger_message: str
    trigger_message_type: str
    conversation_id: str
    display_name: str
    remark_name: str
    local_id: str
    _identity: Any
    node_settings: dict
    system_prompt: str
    prompt_extensions: list[dict]
    media_observations: list[str]
    retrieved_memories: list[str]
    proactive_mode: str
    max_messages_per_turn: int
    intent: str
    emotion: str
    user_need: str
    relationship_signal: str
    should_reply: bool
    no_reply_reason: str
    reply_strategy: str
    risk_flags: list[str]
    requires_safety_model: bool
    draft_messages: list[str]
    safety_action: str
    safety_reasons: list[str]
    final_messages: list[str]
    done: bool
    raw_output: str
    node_errors: list[str]
