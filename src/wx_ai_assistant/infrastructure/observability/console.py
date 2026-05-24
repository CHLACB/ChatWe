from __future__ import annotations

from datetime import datetime
import traceback
from typing import Any


SEPARATOR = "────────────────────────────────────────"


def print_listener_event(
    event: str,
    target: str | None = None,
    action: str | None = None,
    details: dict | None = None,
) -> None:
    _safe_print(lambda: _print_listener_event(event, target, action, details))


def print_message_snapshot(target: str, messages: list, title: str = "MESSAGES") -> None:
    _safe_print(lambda: _print_message_snapshot(target, messages, title))


def print_ai_decision(run_id: str, target: str, trigger: str, state: dict) -> None:
    _safe_print(lambda: _print_ai_decision(run_id, target, trigger, state))


def print_send_event(
    target: str,
    status: str,
    messages: list[str] | None = None,
    error: str | None = None,
) -> None:
    _safe_print(lambda: _print_send_event(target, status, messages, error))


def print_error_block(title: str, error: Exception | str, details: dict | None = None) -> None:
    _safe_print(lambda: _print_error_block(title, error, details))


def _print_listener_event(event: str, target: str | None, action: str | None, details: dict | None) -> None:
    lines = [
        SEPARATOR,
        f"[LISTENER] {_now()}",
        f"target: {target or '-'}",
        f"event : {event}",
    ]
    if action:
        lines.append(f"action: {action}")
    _append_details(lines, details)
    lines.append(SEPARATOR)
    print("\n".join(lines), flush=True)


def _print_message_snapshot(target: str, messages: list, title: str) -> None:
    lines = [
        SEPARATOR,
        f"[{title}]",
        f"target: {target}",
        f"count : {len(messages)}",
        "",
    ]
    for index, message in enumerate(messages, start=1):
        sender = _message_sender(message)
        content = _message_content(message)
        lines.append(f"  {index}. [{sender}] {_truncate(content, 120)}")
    lines.append(SEPARATOR)
    print("\n".join(lines), flush=True)


def _print_ai_decision(run_id: str, target: str, trigger: str, state: dict) -> None:
    lines = [
        SEPARATOR,
        f"[AI DECISION] run_id={run_id}",
        f"target : {target}",
        f"trigger: {_truncate(trigger, 160)}",
        "",
        f"intent       : {_value(state.get('intent'))}",
        f"emotion      : {_value(state.get('emotion'))}",
        f"user_need    : {_value(state.get('user_need'))}",
        f"relationship : {_value(state.get('relationship_signal'))}",
        f"should_reply : {str(bool(state.get('should_reply', False))).lower()}",
        f"no_reply     : {_value(state.get('no_reply_reason'))}",
        f"strategy     : {_value(state.get('reply_strategy'))}",
        f"safety       : {_value(state.get('safety_action'))}",
    ]
    _append_list(lines, "safety_reasons", state.get("safety_reasons"))
    _append_summary(lines, "contact_policy", state.get("contact_policy"))
    _append_summary(lines, "conversation_profile", state.get("conversation_profile"))
    _append_list(lines, "draft", state.get("draft_messages"))
    _append_list(lines, "final", state.get("final_messages"))
    _append_list(lines, "node_errors", state.get("node_errors"))
    lines.append(SEPARATOR)
    print("\n".join(lines), flush=True)


def _print_send_event(target: str, status: str, messages: list[str] | None, error: str | None) -> None:
    lines = [
        SEPARATOR,
        "[SEND]",
        f"target: {target}",
        f"status: {status}",
    ]
    _append_list(lines, "messages", messages)
    if error:
        lines.extend(["error:", f"  {_truncate(error, 300)}"])
    lines.append(SEPARATOR)
    print("\n".join(lines), flush=True)


def _print_error_block(title: str, error: Exception | str, details: dict | None) -> None:
    lines = [
        SEPARATOR,
        f"[{title}]",
        f"error: {_truncate(str(error), 500)}",
    ]
    _append_details(lines, details)
    lines.append(SEPARATOR)
    print("\n".join(lines), flush=True)


def _safe_print(callback) -> None:
    try:
        callback()
    except Exception as exc:
        try:
            print(f"warning console_format_failed error={exc}", flush=True)
        except Exception:
            pass


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append_details(lines: list[str], details: dict | None) -> None:
    if not details:
        return
    lines.append("details:")
    for key, value in details.items():
        lines.append(f"  {key}: {_summarize(value)}")


def _append_summary(lines: list[str], title: str, value: Any) -> None:
    if not value:
        return
    lines.append(f"{title}: {_summarize(value)}")


def _append_list(lines: list[str], title: str, value: Any) -> None:
    items = value if isinstance(value, list) else []
    if not items:
        return
    lines.append(f"{title}:")
    for item in items:
        lines.append(f"  - {_truncate(str(item), 160)}")


def _message_sender(message: Any) -> str:
    sender = _get(message, "sender_type", "")
    if not sender:
        sender = _get(message, "sender", "")
    if hasattr(sender, "value"):
        sender = sender.value
    mapping = {"other": "friend", "self": "self", "system": "system", "unknown": "unknown"}
    return mapping.get(str(sender), str(sender) or "unknown")


def _message_content(message: Any) -> str:
    return str(_get(message, "content", ""))


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _value(value: Any) -> str:
    return _truncate(str(value or "-"), 160)


def _truncate(text: str, max_chars: int) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 1)].rstrip() + "…"


def _summarize(value: Any) -> str:
    if isinstance(value, dict):
        pieces = []
        for key in [
            "name",
            "relationship",
            "communication_style",
            "initiative_level",
            "proactive_mode",
            "max_messages",
            "max_chars_per_message",
            "max_messages_per_turn",
            "tone",
        ]:
            if key in value:
                pieces.append(f"{key}={value[key]}")
        return _truncate(", ".join(pieces) if pieces else f"{len(value)} fields", 180)
    if isinstance(value, list):
        return _truncate(f"{len(value)} items", 80)
    if isinstance(value, BaseException):
        return _truncate(str(value), 180)
    return _truncate(str(value), 180)


def format_traceback(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))
