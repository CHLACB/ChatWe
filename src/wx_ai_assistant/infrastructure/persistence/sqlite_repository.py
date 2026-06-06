from __future__ import annotations

import sqlite3
import threading
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from wx_ai_assistant.domain.enums import (
    ConversationType, ListenStatus, MessageSource, MessageType,
    SenderType, SendTaskStatus,
)
from wx_ai_assistant.domain.models import AiDecisionLog, ConversationIdentity, ListenTarget, Message, SendTask, utc_now


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _str_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SqliteRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def initialize_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                conversation_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                remark_name TEXT,
                local_id TEXT,
                last_verified_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS listen_targets (
                conversation_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                sender_type TEXT NOT NULL,
                sender_name TEXT,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                media_path TEXT,
                media_mime_type TEXT,
                media_description TEXT,
                source TEXT NOT NULL,
                raw_id TEXT,
                fingerprint TEXT,
                created_at TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_fingerprint
                ON messages(conversation_id, fingerprint)
                WHERE fingerprint IS NOT NULL;

            CREATE TABLE IF NOT EXISTS send_tasks (
                send_task_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                content TEXT NOT NULL,
                trigger_message_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS ai_decision_logs (
                run_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                trigger_message_id TEXT NOT NULL,
                trigger_message TEXT NOT NULL,
                display_name TEXT NOT NULL,
                contact_policy TEXT NOT NULL,
                conversation_profile TEXT NOT NULL DEFAULT '{}',
                intent TEXT,
                emotion TEXT,
                user_need TEXT,
                relationship_signal TEXT,
                should_reply INTEGER NOT NULL,
                no_reply_reason TEXT,
                reply_strategy TEXT,
                draft_messages TEXT NOT NULL,
                safety_action TEXT,
                safety_reasons TEXT NOT NULL,
                final_messages TEXT NOT NULL,
                done INTEGER NOT NULL,
                node_errors TEXT NOT NULL,
                raw_state TEXT NOT NULL,
                raw_state_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """)
            self._ensure_message_media_columns()
            self._ensure_ai_decision_log_columns()

    def upsert_conversation(self, identity: ConversationIdentity) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO conversations(conversation_id, conversation_type, display_name, remark_name, local_id, last_verified_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    conversation_type=excluded.conversation_type,
                    display_name=excluded.display_name,
                    remark_name=excluded.remark_name,
                    local_id=excluded.local_id,
                    last_verified_at=excluded.last_verified_at,
                    updated_at=excluded.updated_at
                """,
                (
                    identity.conversation_id,
                    identity.conversation_type.value,
                    identity.display_name,
                    identity.remark_name,
                    identity.local_id,
                    _dt_to_str(identity.last_verified_at),
                    _dt_to_str(utc_now()),
                ),
            )

    def get_conversation(self, conversation_id: str) -> Optional[ConversationIdentity]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
        return self._row_to_conversation(row) if row else None

    def list_conversations(self) -> list[ConversationIdentity]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
        return [self._row_to_conversation(r) for r in rows]

    def upsert_listen_target(self, target: ListenTarget) -> None:
        self.upsert_conversation(target.conversation)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO listen_targets(conversation_id, status, last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    status=excluded.status,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (
                    target.conversation.conversation_id,
                    target.status.value,
                    target.last_error,
                    _dt_to_str(target.created_at),
                    _dt_to_str(utc_now()),
                ),
            )

    def set_listen_status(self, conversation_id: str, status: ListenStatus, last_error: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE listen_targets SET status=?, last_error=?, updated_at=? WHERE conversation_id=?",
                (status.value, last_error, _dt_to_str(utc_now()), conversation_id),
            )

    def list_listen_targets(self) -> list[ListenTarget]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT lt.*, c.conversation_type, c.display_name, c.remark_name, c.local_id, c.last_verified_at
                FROM listen_targets lt
                JOIN conversations c ON c.conversation_id = lt.conversation_id
                ORDER BY lt.updated_at DESC
                """
            ).fetchall()
        return [self._row_to_listen_target(r) for r in rows]

    def get_listen_target(self, conversation_id: str) -> Optional[ListenTarget]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT lt.*, c.conversation_type, c.display_name, c.remark_name, c.local_id, c.last_verified_at
                FROM listen_targets lt
                JOIN conversations c ON c.conversation_id = lt.conversation_id
                WHERE lt.conversation_id=?
                """,
                (conversation_id,),
            ).fetchone()
        return self._row_to_listen_target(row) if row else None

    def delete_listen_target(self, conversation_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM listen_targets WHERE conversation_id=?", (conversation_id,))
            return cursor.rowcount > 0

    def insert_message_if_new(self, message: Message) -> bool:
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    """
                    INSERT INTO messages(
                        message_id, conversation_id, sender_type, sender_name,
                        message_type, content, media_path, media_mime_type,
                        media_description, source, raw_id, fingerprint,
                        created_at, received_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.message_id,
                        message.conversation_id,
                        message.sender_type.value,
                        message.sender_name,
                        message.message_type.value,
                        message.content,
                        message.media_path,
                        message.media_mime_type,
                        message.media_description,
                        message.source.value,
                        message.raw_id,
                        message.fingerprint,
                        _dt_to_str(message.created_at),
                        _dt_to_str(message.received_at),
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def list_recent_messages(self, conversation_id: str, limit: int = 50) -> list[Message]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return list(reversed([self._row_to_message(r) for r in rows]))

    def create_send_task(self, task: SendTask) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO send_tasks(send_task_id, conversation_id, content, trigger_message_id, status, created_at, sent_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.send_task_id,
                    task.conversation_id,
                    task.content,
                    task.trigger_message_id,
                    task.status.value,
                    _dt_to_str(task.created_at),
                    _dt_to_str(task.sent_at),
                    task.error_message,
                ),
            )

    def update_send_task(self, task_id: str, status: SendTaskStatus, error_message: str | None = None) -> None:
        sent_at = _dt_to_str(utc_now()) if status == SendTaskStatus.SUCCESS else None
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE send_tasks SET status=?, sent_at=COALESCE(?, sent_at), error_message=? WHERE send_task_id=?",
                (status.value, sent_at, error_message, task_id),
            )

    def reset_send_task_for_retry(self, task_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE send_tasks
                SET status=?, sent_at=NULL, error_message=NULL
                WHERE send_task_id=? AND status=?
                """,
                (SendTaskStatus.PENDING.value, task_id, SendTaskStatus.FAILED.value),
            )
            return cursor.rowcount > 0

    def fail_unfinished_send_tasks(self, error_message: str) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE send_tasks
                SET status=?, error_message=?
                WHERE status IN (?, ?)
                """,
                (
                    SendTaskStatus.FAILED.value,
                    error_message,
                    SendTaskStatus.PENDING.value,
                    SendTaskStatus.SENDING.value,
                ),
            )
            return int(cursor.rowcount or 0)

    def list_pending_send_tasks(self, limit: int = 20) -> list[SendTask]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM send_tasks WHERE status=? ORDER BY created_at ASC LIMIT ?",
                (SendTaskStatus.PENDING.value, limit),
            ).fetchall()
        return [self._row_to_send_task(r) for r in rows]

    def list_send_tasks(
        self,
        conversation_id: str | None = None,
        status: SendTaskStatus | None = None,
        limit: int = 50,
    ) -> list[SendTask]:
        query = "SELECT * FROM send_tasks"
        clauses: list[str] = []
        params: list[str | int] = []
        if conversation_id:
            clauses.append("conversation_id=?")
            params.append(conversation_id)
        if status:
            clauses.append("status=?")
            params.append(status.value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_send_task(r) for r in rows]

    def get_send_task(self, send_task_id: str) -> Optional[SendTask]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM send_tasks WHERE send_task_id=?", (send_task_id,)).fetchone()
        return self._row_to_send_task(row) if row else None

    def save_ai_decision_log(self, log: AiDecisionLog) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO ai_decision_logs(
                    run_id, conversation_id, trigger_message_id, trigger_message, display_name,
                    contact_policy, conversation_profile, intent, emotion, user_need, relationship_signal,
                    should_reply, no_reply_reason, reply_strategy, draft_messages,
                    safety_action, safety_reasons, final_messages, done, node_errors,
                    raw_state, raw_state_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.run_id,
                    log.conversation_id,
                    log.trigger_message_id,
                    log.trigger_message,
                    log.display_name,
                    json.dumps(log.contact_policy, ensure_ascii=False),
                    json.dumps(log.conversation_profile, ensure_ascii=False),
                    log.intent,
                    log.emotion,
                    log.user_need,
                    log.relationship_signal,
                    1 if log.should_reply else 0,
                    log.no_reply_reason,
                    log.reply_strategy,
                    json.dumps(log.draft_messages, ensure_ascii=False),
                    log.safety_action,
                    json.dumps(log.safety_reasons, ensure_ascii=False),
                    json.dumps(log.final_messages, ensure_ascii=False),
                    1 if log.done else 0,
                    json.dumps(log.node_errors, ensure_ascii=False),
                    json.dumps(log.raw_state, ensure_ascii=False),
                    json.dumps(log.raw_state_json or log.raw_state, ensure_ascii=False),
                    _dt_to_str(log.created_at),
                ),
            )

    def clear_conversation_memory(self, conversation_id: str) -> dict[str, int]:
        with self._lock, self._conn:
            messages = self._conn.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,)).rowcount
            ai_logs = self._conn.execute("DELETE FROM ai_decision_logs WHERE conversation_id=?", (conversation_id,)).rowcount
            send_tasks = self._conn.execute("DELETE FROM send_tasks WHERE conversation_id=?", (conversation_id,)).rowcount
        return {
            "messages": int(messages or 0),
            "ai_decision_logs": int(ai_logs or 0),
            "send_tasks": int(send_tasks or 0),
        }

    def list_ai_decision_logs(
        self,
        conversation_id: str | None = None,
        run_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        query = "SELECT * FROM ai_decision_logs"
        clauses: list[str] = []
        params: list[str | int] = []
        if conversation_id:
            clauses.append("conversation_id=?")
            params.append(conversation_id)
        if run_id:
            clauses.append("run_id=?")
            params.append(run_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, limit))
        with self._lock:
            rows = self._conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_ai_decision_log(row) for row in rows]

    def _ensure_message_media_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(messages)").fetchall()
        columns = {row["name"] for row in rows}
        if "media_path" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN media_path TEXT")
        if "media_mime_type" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN media_mime_type TEXT")
        if "media_description" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN media_description TEXT")

    def _ensure_ai_decision_log_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(ai_decision_logs)").fetchall()
        columns = {row["name"] for row in rows}
        if "conversation_profile" not in columns:
            self._conn.execute("ALTER TABLE ai_decision_logs ADD COLUMN conversation_profile TEXT NOT NULL DEFAULT '{}'")
        if "raw_state_json" not in columns:
            self._conn.execute("ALTER TABLE ai_decision_logs ADD COLUMN raw_state_json TEXT NOT NULL DEFAULT '{}'")

    def _row_to_ai_decision_log(self, row: sqlite3.Row) -> dict:
        def decode_json(key: str, default):
            try:
                return json.loads(row[key]) if row[key] else default
            except Exception:
                return default

        raw_state_json = decode_json("raw_state_json", decode_json("raw_state", {}))
        return {
            "run_id": row["run_id"],
            "conversation_id": row["conversation_id"],
            "trigger_message_id": row["trigger_message_id"],
            "trigger_message": row["trigger_message"],
            "display_name": row["display_name"],
            "contact_policy": decode_json("contact_policy", {}),
            "conversation_profile": decode_json("conversation_profile", {}),
            "intent": row["intent"],
            "emotion": row["emotion"],
            "user_need": row["user_need"],
            "relationship_signal": row["relationship_signal"],
            "should_reply": bool(row["should_reply"]),
            "no_reply_reason": row["no_reply_reason"],
            "reply_strategy": row["reply_strategy"],
            "draft_messages": decode_json("draft_messages", []),
            "safety_action": row["safety_action"],
            "safety_reasons": decode_json("safety_reasons", []),
            "final_messages": decode_json("final_messages", []),
            "done": bool(row["done"]),
            "node_errors": decode_json("node_errors", []),
            "risk_flags": raw_state_json.get("risk_flags", []) if isinstance(raw_state_json, dict) else [],
            "requires_safety_model": bool(raw_state_json.get("requires_safety_model", False)) if isinstance(raw_state_json, dict) else False,
            "media_observations": raw_state_json.get("media_observations", []) if isinstance(raw_state_json, dict) else [],
            "retrieved_memories": raw_state_json.get("retrieved_memories", []) if isinstance(raw_state_json, dict) else [],
            "node_settings": raw_state_json.get("node_settings", {}) if isinstance(raw_state_json, dict) else {},
            "raw_state_json": raw_state_json,
            "created_at": row["created_at"],
        }

    def _row_to_conversation(self, row: sqlite3.Row) -> ConversationIdentity:
        return ConversationIdentity(
            conversation_id=row["conversation_id"],
            conversation_type=ConversationType(row["conversation_type"]),
            display_name=row["display_name"],
            remark_name=row["remark_name"],
            local_id=row["local_id"],
            last_verified_at=_str_to_dt(row["last_verified_at"]),
        )

    def _row_to_listen_target(self, row: sqlite3.Row) -> ListenTarget:
        return ListenTarget(
            conversation=ConversationIdentity(
                conversation_id=row["conversation_id"],
                conversation_type=ConversationType(row["conversation_type"]),
                display_name=row["display_name"],
                remark_name=row["remark_name"],
                local_id=row["local_id"],
                last_verified_at=_str_to_dt(row["last_verified_at"]),
            ),
            status=ListenStatus(row["status"]),
            last_error=row["last_error"],
            created_at=_str_to_dt(row["created_at"]) or utc_now(),
            updated_at=_str_to_dt(row["updated_at"]) or utc_now(),
        )

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        return Message(
            message_id=row["message_id"],
            conversation_id=row["conversation_id"],
            sender_type=SenderType(row["sender_type"]),
            sender_name=row["sender_name"],
            message_type=MessageType(row["message_type"]),
            content=row["content"],
            media_path=row["media_path"] if "media_path" in row.keys() else None,
            media_mime_type=row["media_mime_type"] if "media_mime_type" in row.keys() else None,
            media_description=row["media_description"] if "media_description" in row.keys() else None,
            source=MessageSource(row["source"]),
            raw_id=row["raw_id"],
            fingerprint=row["fingerprint"],
            created_at=_str_to_dt(row["created_at"]) or utc_now(),
            received_at=_str_to_dt(row["received_at"]) or utc_now(),
        )

    def _row_to_send_task(self, row: sqlite3.Row) -> SendTask:
        return SendTask(
            send_task_id=row["send_task_id"],
            conversation_id=row["conversation_id"],
            content=row["content"],
            trigger_message_id=row["trigger_message_id"],
            status=SendTaskStatus(row["status"]),
            created_at=_str_to_dt(row["created_at"]) or utc_now(),
            sent_at=_str_to_dt(row["sent_at"]),
            error_message=row["error_message"],
        )
