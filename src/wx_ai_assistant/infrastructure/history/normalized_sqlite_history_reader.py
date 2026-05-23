from __future__ import annotations

import sqlite3
from pathlib import Path

from wx_ai_assistant.domain.enums import MessageSource, MessageType, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.ports.history_reader import HistoryReader, HistoryResult


class NormalizedSqliteHistoryReader(HistoryReader):
    """Reads a normalized history database.

    This deliberately does not guess WeChat's real database schema. Convert your
    decrypted/parsed WeChat history into the normalized_messages table first, or
    implement another HistoryReader adapter.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def read_history(self, identity: ConversationIdentity, limit: int = 100) -> HistoryResult:
        if not self.db_path.exists():
            return HistoryResult(ok=False, messages=[], error=f"标准化历史库不存在: {self.db_path}")
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM normalized_messages
                WHERE conversation_local_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (identity.local_id or identity.conversation_id, limit),
            ).fetchall()
            conn.close()
            messages = []
            for row in reversed(rows):
                messages.append(Message(
                    conversation_id=identity.conversation_id,
                    sender_type=SenderType(row["sender_type"]),
                    sender_name=row["sender_name"],
                    message_type=MessageType.TEXT if row["msg_type"] == "text" else MessageType.UNSUPPORTED,
                    content=row["content"] or "",
                    source=MessageSource.HISTORY,
                    raw_id=row["raw_id"],
                ))
            return HistoryResult(ok=True, messages=messages)
        except Exception as exc:
            return HistoryResult(ok=False, messages=[], error=str(exc))
