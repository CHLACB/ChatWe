from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from wx_ai_assistant.application.strategy_analysis import (
    StrategyDocument,
    StrategyExtractedBlock,
    StrategyKnowledgeChunk,
    StrategyKnowledgeVector,
    utc_now,
)


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _str_to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class SqliteStrategyKnowledgeStore:
    """Separate persistence for strategy-analysis knowledge.

    It shares the app database file but owns its tables. The existing message,
    policy and send-task tables are untouched.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def initialize_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategy_knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    original_filename TEXT NOT NULL DEFAULT '',
                    storage_path TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL,
                    knowledge_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    parse_status TEXT NOT NULL DEFAULT 'success',
                    parse_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_knowledge_blocks (
                    block_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    block_index INTEGER NOT NULL,
                    block_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source_location TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES strategy_knowledge_documents(document_id)
                );

                CREATE TABLE IF NOT EXISTS strategy_knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_location TEXT NOT NULL DEFAULT '',
                    source_locations_json TEXT NOT NULL DEFAULT '[]',
                    tags_json TEXT NOT NULL,
                    knowledge_type TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    embedding_model TEXT,
                    embedding_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES strategy_knowledge_documents(document_id)
                );

                CREATE INDEX IF NOT EXISTS idx_strategy_chunks_document
                    ON strategy_knowledge_chunks(document_id, chunk_index);
                CREATE INDEX IF NOT EXISTS idx_strategy_chunks_type
                    ON strategy_knowledge_chunks(knowledge_type);

                CREATE TABLE IF NOT EXISTS strategy_knowledge_vectors (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(chunk_id) REFERENCES strategy_knowledge_chunks(chunk_id),
                    FOREIGN KEY(document_id) REFERENCES strategy_knowledge_documents(document_id)
                );

                CREATE INDEX IF NOT EXISTS idx_strategy_vectors_namespace
                    ON strategy_knowledge_vectors(namespace, embedding_model);

                CREATE TABLE IF NOT EXISTS contact_knowledge_bindings (
                    conversation_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    document_ids_json TEXT NOT NULL,
                    tag_filters_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_schema_columns()

    def add_document(
        self,
        document: StrategyDocument,
        blocks: list[StrategyExtractedBlock],
        chunks: list[StrategyKnowledgeChunk],
    ) -> StrategyDocument:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO strategy_knowledge_documents(
                    document_id, title, content, source_type, original_filename, storage_path,
                    content_hash, tags_json, knowledge_type, status, parse_status, parse_error,
                    updated_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    document.title,
                    document.content,
                    document.source_type,
                    document.original_filename,
                    document.storage_path,
                    document.content_hash,
                    json.dumps(document.tags, ensure_ascii=False),
                    document.knowledge_type,
                    document.status,
                    document.parse_status,
                    document.parse_error,
                    _dt_to_str(document.updated_at),
                    _dt_to_str(document.created_at),
                ),
            )
            self._insert_blocks(blocks)
            for chunk in chunks:
                self._insert_chunk(chunk)
        return document

    def list_documents(self, limit: int = 50) -> list[StrategyDocument]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM strategy_knowledge_documents
                WHERE status != 'deleted'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def get_document(self, document_id: str) -> StrategyDocument | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM strategy_knowledge_documents WHERE document_id=? AND status != 'deleted'",
                (document_id,),
            ).fetchone()
        return self._row_to_document(row) if row else None

    def update_document_status(self, document_id: str, status: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE strategy_knowledge_documents
                SET status=?, updated_at=?
                WHERE document_id=? AND status != 'deleted'
                """,
                (status, _dt_to_str(utc_now()), document_id),
            )
            return cursor.rowcount > 0

    def delete_document(self, document_id: str) -> bool:
        return self.update_document_status(document_id, "deleted")

    def replace_document_index(
        self,
        document_id: str,
        blocks: list[StrategyExtractedBlock],
        chunks: list[StrategyKnowledgeChunk],
    ) -> bool:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT document_id FROM strategy_knowledge_documents WHERE document_id=? AND status != 'deleted'",
                (document_id,),
            ).fetchone()
            if row is None:
                return False
            self._conn.execute("DELETE FROM strategy_knowledge_vectors WHERE document_id=?", (document_id,))
            self._conn.execute("DELETE FROM strategy_knowledge_chunks WHERE document_id=?", (document_id,))
            self._conn.execute("DELETE FROM strategy_knowledge_blocks WHERE document_id=?", (document_id,))
            self._insert_blocks(blocks)
            for chunk in chunks:
                self._insert_chunk(chunk)
            self._conn.execute(
                "UPDATE strategy_knowledge_documents SET updated_at=? WHERE document_id=?",
                (_dt_to_str(utc_now()), document_id),
            )
            return True

    def list_chunks(self, document_id: str | None = None, limit: int = 100) -> list[StrategyKnowledgeChunk]:
        params: list[object] = []
        where = "WHERE c.enabled=1 AND d.status='active' AND d.parse_status IN ('success', 'partial')"
        if document_id:
            where += " AND c.document_id=?"
            params.append(document_id)
        params.append(max(1, limit))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT c.*
                FROM strategy_knowledge_chunks c
                JOIN strategy_knowledge_documents d ON d.document_id = c.document_id
                {where}
                ORDER BY c.created_at DESC, c.chunk_index ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def upsert_chunk_vector(self, vector: StrategyKnowledgeVector) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO strategy_knowledge_vectors(
                    chunk_id, document_id, namespace, embedding_model, dimensions,
                    vector_json, metadata_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    document_id=excluded.document_id,
                    namespace=excluded.namespace,
                    embedding_model=excluded.embedding_model,
                    dimensions=excluded.dimensions,
                    vector_json=excluded.vector_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    vector.chunk_id,
                    vector.document_id,
                    vector.namespace,
                    vector.embedding_model,
                    vector.dimensions,
                    json.dumps(vector.vector),
                    json.dumps(vector.metadata, ensure_ascii=False),
                    _dt_to_str(vector.updated_at),
                ),
            )

    def list_chunk_vectors(
        self,
        namespace: str = "ai_document_knowledge",
        limit: int = 1000,
        document_ids: list[str] | None = None,
    ) -> list[StrategyKnowledgeVector]:
        params: list[object] = [namespace]
        document_ids = [item for item in document_ids or [] if item]
        document_filter = ""
        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            document_filter = f" AND v.document_id IN ({placeholders})"
            params.extend(document_ids)
        params.append(max(1, limit))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT v.* FROM strategy_knowledge_vectors v
                JOIN strategy_knowledge_documents d ON d.document_id = v.document_id
                JOIN strategy_knowledge_chunks c ON c.chunk_id = v.chunk_id
                WHERE v.namespace=? AND d.status='active' AND c.enabled=1{document_filter}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_vector(row) for row in rows]

    def get_contact_knowledge_settings(self, conversation_id: str) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM contact_knowledge_bindings WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            return {
                "conversation_id": conversation_id,
                "enabled": False,
                "document_ids": [],
                "tag_filters": [],
            }
        return {
            "conversation_id": conversation_id,
            "enabled": bool(row["enabled"]),
            "document_ids": json.loads(row["document_ids_json"] or "[]"),
            "tag_filters": json.loads(row["tag_filters_json"] or "[]"),
            "updated_at": row["updated_at"],
        }

    def set_contact_knowledge_settings(
        self,
        conversation_id: str,
        enabled: bool,
        document_ids: list[str] | None = None,
        tag_filters: list[str] | None = None,
    ) -> dict:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO contact_knowledge_bindings(
                    conversation_id, enabled, document_ids_json, tag_filters_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    document_ids_json=excluded.document_ids_json,
                    tag_filters_json=excluded.tag_filters_json,
                    updated_at=excluded.updated_at
                """,
                (
                    conversation_id,
                    1 if enabled else 0,
                    json.dumps(document_ids or [], ensure_ascii=False),
                    json.dumps(tag_filters or [], ensure_ascii=False),
                    _dt_to_str(utc_now()),
                ),
            )
        return self.get_contact_knowledge_settings(conversation_id)

    def _insert_blocks(self, blocks: list[StrategyExtractedBlock]) -> None:
        for block in blocks:
            self._conn.execute(
                """
                INSERT INTO strategy_knowledge_blocks(
                    block_id, document_id, block_index, block_type, text,
                    source_location, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    block.block_id,
                    block.document_id,
                    block.block_index,
                    block.block_type,
                    block.text,
                    block.source_location,
                    json.dumps(block.metadata, ensure_ascii=False),
                    _dt_to_str(block.created_at),
                ),
            )

    def _insert_chunk(self, chunk: StrategyKnowledgeChunk) -> None:
        self._conn.execute(
            """
            INSERT INTO strategy_knowledge_chunks(
                chunk_id, document_id, chunk_text, chunk_index, title, source_type,
                source_location, source_locations_json, tags_json, knowledge_type,
                enabled, embedding_model, embedding_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.document_id,
                chunk.chunk_text,
                chunk.chunk_index,
                chunk.title,
                chunk.source_type,
                chunk.source_location,
                json.dumps(chunk.source_locations, ensure_ascii=False),
                json.dumps(chunk.tags, ensure_ascii=False),
                chunk.knowledge_type,
                1 if chunk.enabled else 0,
                None,
                None,
                _dt_to_str(chunk.created_at),
            ),
        )

    def _ensure_schema_columns(self) -> None:
        for table, columns in {
            "strategy_knowledge_documents": {
                "original_filename": "TEXT NOT NULL DEFAULT ''",
                "storage_path": "TEXT NOT NULL DEFAULT ''",
                "content_hash": "TEXT NOT NULL DEFAULT ''",
                "status": "TEXT NOT NULL DEFAULT 'active'",
                "parse_status": "TEXT NOT NULL DEFAULT 'success'",
                "parse_error": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            },
            "strategy_knowledge_chunks": {
                "source_location": "TEXT NOT NULL DEFAULT ''",
                "source_locations_json": "TEXT NOT NULL DEFAULT '[]'",
                "enabled": "INTEGER NOT NULL DEFAULT 1",
            },
        }.items():
            existing = {
                row["name"]
                for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for name, ddl in columns.items():
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _row_to_document(self, row: sqlite3.Row) -> StrategyDocument:
        return StrategyDocument(
            document_id=row["document_id"],
            title=row["title"],
            content=row["content"],
            source_type=row["source_type"],
            original_filename=row["original_filename"],
            storage_path=row["storage_path"],
            content_hash=row["content_hash"],
            tags=json.loads(row["tags_json"] or "[]"),
            knowledge_type=row["knowledge_type"],
            status=row["status"],
            parse_status=row["parse_status"],
            parse_error=row["parse_error"],
            created_at=_str_to_dt(row["created_at"]) or datetime.now(),
            updated_at=_str_to_dt(row["updated_at"]) or _str_to_dt(row["created_at"]) or datetime.now(),
        )

    def _row_to_chunk(self, row: sqlite3.Row) -> StrategyKnowledgeChunk:
        return StrategyKnowledgeChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            title=row["title"],
            source_type=row["source_type"],
            source_location=row["source_location"],
            source_locations=json.loads(row["source_locations_json"] or "[]"),
            tags=json.loads(row["tags_json"] or "[]"),
            knowledge_type=row["knowledge_type"],
            enabled=bool(row["enabled"]),
            chunk_text=row["chunk_text"],
            chunk_index=row["chunk_index"],
            score=0.0,
            vector_score=0.0,
            lexical_score=0.0,
            score_source="",
            created_at=_str_to_dt(row["created_at"]) or datetime.now(),
        )

    def _row_to_vector(self, row: sqlite3.Row) -> StrategyKnowledgeVector:
        return StrategyKnowledgeVector(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            namespace=row["namespace"],
            embedding_model=row["embedding_model"],
            dimensions=row["dimensions"],
            vector=json.loads(row["vector_json"] or "[]"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            updated_at=_str_to_dt(row["updated_at"]) or datetime.now(),
        )
