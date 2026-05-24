from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.core.config import load_settings  # noqa: E402
from wx_ai_assistant.infrastructure.observability.console import print_ai_decision, print_listener_event  # noqa: E402
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Show formatted LangGraph AI decision logs.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--conversation", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--db-path", default="")
    args = parser.parse_args()

    settings = load_settings()
    db_path = Path(args.db_path) if args.db_path else settings.db_path
    repo = SqliteRepository(db_path)
    repo.initialize_schema()

    rows = _query_rows(repo._conn, args.limit, args.conversation, args.run_id)
    if not rows:
        print_listener_event("ai_decision_logs_empty", details={"db_path": str(db_path)})
        return 0

    for row in rows:
        state = _row_to_state(row)
        print_listener_event(
            "ai_decision_log",
            target=row["display_name"],
            details={
                "created_at": row["created_at"],
                "conversation_id": row["conversation_id"],
                "run_id": row["run_id"],
            },
        )
        print_ai_decision(row["run_id"], row["display_name"], row["trigger_message"], state)
        if args.run_id:
            raw_state = _json(row["raw_state_json"]) or _json(row["raw_state"])
            print_listener_event(
                "ai_decision_log_detail",
                target=row["display_name"],
                details={
                    "user_need": state.get("user_need", ""),
                    "relationship_signal": state.get("relationship_signal", ""),
                    "contact_policy": _summary(state.get("contact_policy")),
                    "conversation_profile": _summary(state.get("conversation_profile")),
                    "node_errors": state.get("node_errors", []),
                    "raw_state_keys": sorted(raw_state.keys()) if isinstance(raw_state, dict) else [],
                },
            )
    return 0


def _query_rows(conn: sqlite3.Connection, limit: int, conversation: str, run_id: str) -> list[sqlite3.Row]:
    query = "SELECT * FROM ai_decision_logs"
    clauses: list[str] = []
    params: list[Any] = []
    if run_id:
        clauses.append("run_id=?")
        params.append(run_id)
    if conversation:
        clauses.append("(conversation_id=? OR display_name=?)")
        params.extend([conversation, conversation])
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, limit))
    return list(conn.execute(query, params).fetchall())


def _row_to_state(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "intent": row["intent"],
        "emotion": row["emotion"],
        "user_need": row["user_need"],
        "relationship_signal": row["relationship_signal"],
        "should_reply": bool(row["should_reply"]),
        "no_reply_reason": row["no_reply_reason"],
        "reply_strategy": row["reply_strategy"],
        "draft_messages": _json(row["draft_messages"]) or [],
        "safety_action": row["safety_action"],
        "safety_reasons": _json(row["safety_reasons"]) or [],
        "final_messages": _json(row["final_messages"]) or [],
        "node_errors": _json(row["node_errors"]) or [],
        "contact_policy": _json(row["contact_policy"]) or {},
        "conversation_profile": _json(row["conversation_profile"]) or {},
    }


def _json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _summary(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "")
    keys = [
        "name",
        "relationship",
        "communication_style",
        "initiative_level",
        "max_messages",
        "max_chars_per_message",
        "max_messages_per_turn",
        "tone",
    ]
    return ", ".join(f"{key}={value[key]}" for key in keys if key in value)


if __name__ == "__main__":
    raise SystemExit(main())
