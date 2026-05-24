from __future__ import annotations

from typing import TypedDict


class WechatReplyState(TypedDict, total=False):
    context: str
    trigger_message: str
    conversation_id: str
    display_name: str
    proactive_mode: str
    max_messages_per_turn: int
    intent: str
    emotion: str
    user_need: str
    relationship_signal: str
    should_reply: bool
    no_reply_reason: str
    reply_strategy: str
    draft_messages: list[str]
    safety_action: str
    safety_reasons: list[str]
    final_messages: list[str]
    done: bool
    raw_output: str
