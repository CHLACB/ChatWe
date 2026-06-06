from __future__ import annotations

import json
import urllib.error
import urllib.request
import base64
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from wx_ai_assistant.core.text_sanitize import sanitize_text
from wx_ai_assistant.core.text_sanitize import sanitize_jsonable
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.ports.repository import Repository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StrategyDocument:
    title: str
    content: str
    source_type: str = "text"
    original_filename: str = ""
    storage_path: str = ""
    content_hash: str = ""
    tags: list[str] = field(default_factory=list)
    knowledge_type: str = "unlabeled"
    status: str = "active"
    parse_status: str = "success"
    parse_error: str = ""
    document_id: str = field(default_factory=lambda: "kdoc_" + uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class StrategyExtractedBlock:
    document_id: str
    block_index: int
    block_type: str
    text: str
    source_location: str = ""
    metadata: dict = field(default_factory=dict)
    block_id: str = field(default_factory=lambda: "kblock_" + uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class StrategyKnowledgeChunk:
    document_id: str
    chunk_text: str
    chunk_index: int
    title: str = ""
    source_type: str = "text"
    source_location: str = ""
    source_locations: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    knowledge_type: str = "unlabeled"
    enabled: bool = True
    chunk_id: str = field(default_factory=lambda: "kchunk_" + uuid4().hex)
    score: float = 0.0
    vector_score: float = 0.0
    lexical_score: float = 0.0
    score_source: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class StrategyKnowledgeVector:
    chunk_id: str
    document_id: str
    embedding_model: str
    dimensions: int
    vector: list[float]
    namespace: str = "ai_document_knowledge"
    metadata: dict = field(default_factory=dict)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class StrategyAnalysisReport:
    conversation: dict
    message_count: int
    instruction: str
    intent: str
    needs: list[str]
    relationship_signal: str
    risks: list[str]
    suggested_strategy: str
    reply_examples: list[str]
    matched_knowledge: list[dict]
    no_send: bool = True
    user_direction: str = ""


@dataclass(frozen=True)
class StrategyAnalysisAiConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 1200
    timeout_seconds: float = 30
    extra_body: str = ""


@dataclass(frozen=True)
class StrategyEmbeddingConfig:
    base_url: str
    api_key: str
    model: str = "tongyi-embedding-vision-flash-2026-03-06"
    dimensions: int = 768
    timeout_seconds: float = 30


class StrategyKnowledgeStore(Protocol):
    def initialize_schema(self) -> None: ...
    def add_document(
        self,
        document: StrategyDocument,
        blocks: list[StrategyExtractedBlock],
        chunks: list[StrategyKnowledgeChunk],
    ) -> StrategyDocument: ...
    def list_documents(self, limit: int = 50) -> list[StrategyDocument]: ...
    def get_document(self, document_id: str) -> StrategyDocument | None: ...
    def update_document_status(self, document_id: str, status: str) -> bool: ...
    def delete_document(self, document_id: str) -> bool: ...
    def replace_document_index(self, document_id: str, blocks: list[StrategyExtractedBlock], chunks: list[StrategyKnowledgeChunk]) -> bool: ...
    def list_chunks(self, document_id: str | None = None, limit: int = 100) -> list[StrategyKnowledgeChunk]: ...
    def upsert_chunk_vector(self, vector: StrategyKnowledgeVector) -> None: ...
    def list_chunk_vectors(
        self,
        namespace: str = "ai_document_knowledge",
        limit: int = 1000,
        document_ids: list[str] | None = None,
    ) -> list[StrategyKnowledgeVector]: ...
    def get_contact_knowledge_settings(self, conversation_id: str) -> dict: ...
    def set_contact_knowledge_settings(
        self,
        conversation_id: str,
        enabled: bool,
        document_ids: list[str] | None = None,
        tag_filters: list[str] | None = None,
    ) -> dict: ...


class TextEmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


class StrategyAnalysisAi(Protocol):
    def analyze(
        self,
        identity: ConversationIdentity,
        messages: list[Message],
        instruction: str,
        knowledge: list[StrategyKnowledgeChunk],
        user_direction: str = "",
    ) -> StrategyAnalysisReport: ...


class OpenAICompatibleStrategyAnalysisAi:
    def __init__(self, config: StrategyAnalysisAiConfig):
        self.config = config

    def analyze(
        self,
        identity: ConversationIdentity,
        messages: list[Message],
        instruction: str,
        knowledge: list[StrategyKnowledgeChunk],
        user_direction: str = "",
    ) -> StrategyAnalysisReport:
        data = self._complete_json(
            _analysis_system_prompt(),
            _analysis_user_prompt(identity, messages, instruction, knowledge, user_direction),
        )
        return StrategyAnalysisReport(
            conversation=asdict(identity),
            message_count=len(messages),
            instruction=instruction,
            intent=sanitize_text(str(data.get("intent", ""))).strip(),
            needs=_coerce_str_list(data.get("needs")),
            relationship_signal=sanitize_text(str(data.get("relationship_signal", ""))).strip(),
            risks=_coerce_str_list(data.get("risks")),
            suggested_strategy=sanitize_text(str(data.get("suggested_strategy", ""))).strip(),
            reply_examples=_coerce_str_list(data.get("reply_examples")),
            matched_knowledge=[_chunk_to_dict(chunk) for chunk in knowledge],
            no_send=True,
            user_direction=sanitize_text(user_direction).strip(),
        )

    def _complete_json(self, system_prompt: str, user_prompt: str) -> dict:
        if not self.config.api_key:
            raise RuntimeError("APP_AI_API_KEY 为空，策略分析需要配置大模型后才能执行。")
        payload: dict = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.extra_body:
            extra = json.loads(self.config.extra_body)
            if not isinstance(extra, dict):
                raise RuntimeError("APP_AI_EXTRA_BODY 必须是 JSON object")
            payload.update(extra)
        request = urllib.request.Request(
            self._chat_completions_url(),
            data=json.dumps(sanitize_jsonable(payload), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"策略分析 AI HTTP {exc.code}: {error_body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"策略分析 AI 请求失败: {exc}") from exc
        return self._extract_json_object(self._extract_reply_text(json.loads(body)))

    def _chat_completions_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _extract_reply_text(self, data: dict) -> str:
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            text = choices[0].get("text")
            if isinstance(text, str):
                return text
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text
        raise RuntimeError("策略分析 AI 响应中没有文本内容")

    def _extract_json_object(self, text: str) -> dict:
        text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise RuntimeError(f"策略分析 AI 未返回 JSON object: {text[:300]}")
        data = json.loads(match.group(0))
        if not isinstance(data, dict):
            raise RuntimeError("策略分析 AI 返回内容不是 JSON object")
        return data


class DashScopeMultimodalTextEmbeddingProvider:
    """Text embedding provider using DashScope Multimodal-Embedding HTTP API."""

    def __init__(self, config: StrategyEmbeddingConfig):
        self.config = config
        self.model_name = f"{config.model}:d{config.dimensions}"
        self.dimensions = config.dimensions

    def embed(self, text: str) -> list[float]:
        if not self.config.api_key:
            raise RuntimeError("APP_EMBEDDING_API_KEY 为空，文档知识库需要配置真实 embedding 服务。")
        text = sanitize_text(text).strip()
        if not text:
            return [0.0] * self.dimensions
        payload = {
            "model": self.config.model,
            "input": {"contents": [{"text": text}]},
            "parameters": {"dimension": self.dimensions},
        }
        request = urllib.request.Request(
            self._embedding_url(),
            data=json.dumps(sanitize_jsonable(payload), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Embedding 服务 HTTP {exc.code}: {error_body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Embedding 服务请求失败: {exc}") from exc
        data = json.loads(body)
        embeddings = ((data.get("output") or {}).get("embeddings") or [])
        if not embeddings:
            raise RuntimeError(f"Embedding 服务响应中没有 embeddings: {body[:500]}")
        vector = embeddings[0].get("embedding")
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("Embedding 服务返回的 embedding 不是有效数组")
        if len(vector) != self.dimensions:
            raise RuntimeError(f"Embedding 维度不一致: 期望 {self.dimensions}, 实际 {len(vector)}")
        return [float(value) for value in vector]

    def _embedding_url(self) -> str:
        return self.config.base_url.rstrip("/")


class StrategyVectorIndex:
    def __init__(
        self,
        store: StrategyKnowledgeStore,
        embedding_provider: TextEmbeddingProvider | None = None,
        namespace: str = "ai_document_knowledge",
    ):
        if embedding_provider is None:
            raise ValueError("必须配置真实 embedding provider，当前已取消本地 embedding。")
        self.store = store
        self.embedding_provider = embedding_provider
        self.namespace = namespace
        self.last_search_stats: dict = {}

    def index_chunks(self, chunks: list[StrategyKnowledgeChunk]) -> int:
        indexed = 0
        for chunk in chunks:
            text = _chunk_embedding_text(chunk)
            vector = self.embedding_provider.embed(text)
            self.store.upsert_chunk_vector(
                StrategyKnowledgeVector(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    embedding_model=self.embedding_provider.model_name,
                    dimensions=self.embedding_provider.dimensions,
                    vector=vector,
                    namespace=self.namespace,
                    metadata={
                        "title": chunk.title,
                        "knowledge_type": chunk.knowledge_type,
                        "tags": chunk.tags,
                        "chunk_index": chunk.chunk_index,
                        "source_location": chunk.source_location,
                    },
                )
            )
            indexed += 1
        return indexed

    def search(
        self,
        query: str,
        limit: int = 6,
        knowledge_type: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        query_vector = self.embedding_provider.embed(query)
        if not any(query_vector):
            self.last_search_stats = {
                "stored_vectors": 0,
                "usable_vectors": 0,
                "skipped_model_mismatch": 0,
                "vector_hits": 0,
                "document_filter_count": len(document_ids or []),
            }
            return []
        vectors = self.store.list_chunk_vectors(namespace=self.namespace, limit=5000, document_ids=document_ids)
        scored: list[tuple[str, float]] = []
        usable_vectors = 0
        skipped_model_mismatch = 0
        for stored in vectors:
            if stored.embedding_model != self.embedding_provider.model_name:
                skipped_model_mismatch += 1
                continue
            usable_vectors += 1
            if knowledge_type and stored.metadata.get("knowledge_type") != knowledge_type:
                continue
            score = _cosine_similarity(query_vector, stored.vector)
            if score > 0:
                scored.append((stored.chunk_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        result = scored[: max(1, limit)]
        self.last_search_stats = {
            "stored_vectors": len(vectors),
            "usable_vectors": usable_vectors,
            "skipped_model_mismatch": skipped_model_mismatch,
            "vector_hits": len(result),
            "document_filter_count": len(document_ids or []),
        }
        return result


class StrategyKnowledgeRetriever:
    """Hybrid retriever backed by the AI document vector store."""

    def __init__(self, store: StrategyKnowledgeStore, vector_index: StrategyVectorIndex | None = None):
        if vector_index is None:
            raise ValueError("必须配置真实 embedding provider，当前已取消本地 embedding。")
        self.store = store
        self.vector_index = vector_index

    def search(
        self,
        query: str,
        limit: int = 6,
        knowledge_type: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[StrategyKnowledgeChunk]:
        query_terms = _tokenize(query)
        if not query_terms:
            return []
        document_ids = [item for item in document_ids or [] if item]
        if document_ids:
            chunks = []
            for document_id in document_ids:
                chunks.extend(self.store.list_chunks(document_id=document_id, limit=500))
        else:
            chunks = self.store.list_chunks(limit=500)
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        vector_scores = dict(
            self.vector_index.search(
                query,
                limit=max(limit * 3, 12),
                knowledge_type=knowledge_type,
                document_ids=document_ids or None,
            )
        )
        scored_by_id: dict[str, StrategyKnowledgeChunk] = {}
        for chunk in chunks:
            if knowledge_type and chunk.knowledge_type != knowledge_type:
                continue
            vector_score = vector_scores.get(chunk.chunk_id, 0.0)
            lexical_score = _lexical_score(query_terms, chunk)
            score = (vector_score * 0.72) + (min(lexical_score, 4.0) / 4.0 * 0.28)
            if score <= 0:
                continue
            scored_by_id[chunk.chunk_id] = _copy_chunk_with_score(
                chunk,
                score,
                vector_score=vector_score,
                lexical_score=lexical_score,
                score_source="hybrid" if vector_score > 0 and lexical_score > 0 else ("vector" if vector_score > 0 else "lexical"),
            )
        for chunk_id, vector_score in vector_scores.items():
            if chunk_id not in chunks_by_id or chunk_id in scored_by_id:
                continue
            scored_by_id[chunk_id] = _copy_chunk_with_score(
                chunks_by_id[chunk_id],
                vector_score * 0.72,
                vector_score=vector_score,
                lexical_score=0.0,
                score_source="vector",
            )
        scored = list(scored_by_id.values())
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(1, limit)]

    def index_chunks(self, chunks: list[StrategyKnowledgeChunk]) -> int:
        return self.vector_index.index_chunks(chunks)

    def vector_status(self) -> dict:
        return {
            "enabled": True,
            "namespace": self.vector_index.namespace,
            "embedding_model": self.vector_index.embedding_provider.model_name,
            "dimensions": self.vector_index.embedding_provider.dimensions,
            "backend": "sqlite_cosine",
            "provider": "dashscope_multimodal_embedding",
            **self.vector_index.last_search_stats,
        }


class StrategyAnalysisService:
    """Read-only side module for strategy analysis.

    This service does not mutate contact policy/profile JSON and never creates
    send tasks. It is meant to be safe to call from a future "策略分析" page.
    """

    def __init__(
        self,
        repo: Repository,
        store: StrategyKnowledgeStore,
        analyzer: StrategyAnalysisAi,
        upload_dir: Path | str = Path("data/knowledge/uploads"),
        embedding_provider: TextEmbeddingProvider | None = None,
    ):
        self.repo = repo
        self.store = store
        self.analyzer = analyzer
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.retriever = StrategyKnowledgeRetriever(store, StrategyVectorIndex(store, embedding_provider))

    def add_text_document(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        knowledge_type: str = "unknown",
        source_type: str = "text",
    ) -> dict:
        title = sanitize_text(title).strip()
        content = sanitize_text(content).strip()
        if not title:
            raise ValueError("文档标题不能为空")
        if not content:
            raise ValueError("文档内容不能为空")
        _reject_polluted_knowledge_text(content, title)
        saved, chunks = self._store_document(
            title=title,
            content=content,
            blocks=_blocks_from_text(content, "text"),
            source_type=source_type or "text",
            original_filename="",
            storage_path="",
            tags=tags,
            knowledge_type=knowledge_type,
        )
        indexed_count = self.retriever.index_chunks(chunks)
        return {
            "document": _document_to_dict(saved),
            "chunk_count": len(chunks),
            "vector_entry": {**self.retriever.vector_status(), "indexed_count": indexed_count},
        }

    def add_uploaded_document(
        self,
        filename: str,
        content_base64: str,
        title: str | None = None,
        tags: list[str] | None = None,
        knowledge_type: str = "unknown",
    ) -> dict:
        filename = Path(sanitize_text(filename).strip()).name
        if not filename:
            raise ValueError("文件名不能为空")
        raw = base64.b64decode(content_base64)
        if not raw:
            raise ValueError("上传文件为空")
        document_id = "kdoc_" + uuid4().hex
        source_type = _source_type_from_filename(filename)
        safe_name = f"{document_id}_{filename}"
        storage_path = self.upload_dir / safe_name
        storage_path.write_bytes(raw)
        parsed = _parse_document_bytes(raw, filename, source_type)
        content = parsed["content"]
        parse_status = parsed["parse_status"]
        parse_error = parsed["parse_error"]
        blocks = parsed["blocks"]
        display_title = sanitize_text(title or Path(filename).stem).strip() or filename
        if source_type in {"text", "md", "txt"}:
            _reject_polluted_knowledge_text(content, display_title)
        saved, chunks = self._store_document(
            title=display_title,
            content=content,
            blocks=blocks,
            source_type=source_type,
            original_filename=filename,
            storage_path=str(storage_path),
            tags=tags,
            knowledge_type=knowledge_type,
            document_id=document_id,
            parse_status=parse_status,
            parse_error=parse_error,
            content_hash=hashlib.sha256(raw).hexdigest(),
        )
        indexed_count = self.retriever.index_chunks(chunks)
        return {
            "document": _document_to_dict(saved),
            "chunk_count": len(chunks),
            "vector_entry": {**self.retriever.vector_status(), "indexed_count": indexed_count},
        }

    def list_documents(self, limit: int = 50) -> list[dict]:
        return [_document_to_dict(document) for document in self.store.list_documents(limit=limit)]

    def get_document(self, document_id: str) -> dict:
        document = self.store.get_document(document_id)
        if document is None:
            raise ValueError(f"文档不存在: {document_id}")
        chunks = self.store.list_chunks(document_id=document_id, limit=500)
        return {
            "document": _document_to_dict(document),
            "chunks": [_chunk_to_dict(chunk) for chunk in chunks],
        }

    def set_document_enabled(self, document_id: str, enabled: bool) -> dict:
        status = "active" if enabled else "disabled"
        if not self.store.update_document_status(document_id, status):
            raise ValueError(f"文档不存在: {document_id}")
        return self.get_document(document_id)["document"]

    def delete_document(self, document_id: str) -> dict:
        if not self.store.update_document_status(document_id, "deleted"):
            raise ValueError(f"文档不存在: {document_id}")
        return {"document_id": document_id, "status": "deleted"}

    def rebuild_document_index(self, document_id: str) -> dict:
        document = self.store.get_document(document_id)
        if document is None:
            raise ValueError(f"文档不存在: {document_id}")
        if document.storage_path:
            path = Path(document.storage_path)
            if not path.exists():
                raise ValueError("原始文件不存在，无法重建索引")
            parsed = _parse_document_bytes(path.read_bytes(), document.original_filename, document.source_type)
            content = parsed["content"]
            blocks = parsed["blocks"]
        else:
            content = document.content
            blocks = _blocks_from_text(content, document.source_type)
        chunks = _chunks_from_blocks(
            document_id=document.document_id,
            title=document.title,
            source_type=document.source_type,
            tags=document.tags,
            knowledge_type=document.knowledge_type,
            blocks=blocks,
        )
        self.store.replace_document_index(document_id, blocks, chunks)
        indexed_count = self.retriever.index_chunks(chunks)
        return {
            "document": _document_to_dict(document),
            "chunk_count": len(chunks),
            "vector_entry": {**self.retriever.vector_status(), "indexed_count": indexed_count},
        }

    def search_knowledge(
        self,
        query: str,
        limit: int = 6,
        knowledge_type: str | None = None,
        document_ids: list[str] | None = None,
    ) -> dict:
        query = sanitize_text(query).strip()
        if not query:
            raise ValueError("检索文本不能为空")
        document_ids = [sanitize_text(item).strip() for item in document_ids or [] if sanitize_text(item).strip()]
        chunks = self.retriever.search(query, limit=limit, knowledge_type=knowledge_type, document_ids=document_ids)
        return {
            "query": query,
            "matches": [_chunk_to_dict(chunk) for chunk in chunks],
            "retriever": "hybrid_vector_lexical",
            "vector_entry": self.retriever.vector_status(),
            "document_ids": document_ids,
        }

    def get_contact_knowledge_settings(self, conversation_id: str) -> dict:
        if self.repo.get_conversation(conversation_id) is None:
            raise ValueError(f"会话不存在: {conversation_id}")
        return self.store.get_contact_knowledge_settings(conversation_id)

    def set_contact_knowledge_settings(
        self,
        conversation_id: str,
        enabled: bool,
        document_ids: list[str] | None = None,
        tag_filters: list[str] | None = None,
    ) -> dict:
        if self.repo.get_conversation(conversation_id) is None:
            raise ValueError(f"会话不存在: {conversation_id}")
        return self.store.set_contact_knowledge_settings(conversation_id, enabled, document_ids, tag_filters)

    def analyze_conversation(
        self,
        conversation_id: str,
        instruction: str = "",
        user_direction: str = "",
        message_limit: int = 80,
        knowledge_limit: int = 6,
    ) -> StrategyAnalysisReport:
        identity = self.repo.get_conversation(conversation_id)
        if identity is None:
            raise ValueError(f"会话不存在: {conversation_id}")
        instruction = sanitize_text(instruction).strip()
        user_direction = sanitize_text(user_direction).strip()
        messages = self.repo.list_recent_messages(conversation_id, limit=max(1, min(message_limit, 500)))
        query = _analysis_query(identity, messages, instruction, user_direction)
        knowledge = self.retriever.search(query, limit=max(1, min(knowledge_limit, 20)))
        return self.analyzer.analyze(identity, messages, instruction, knowledge, user_direction)

    def _store_document(
        self,
        title: str,
        content: str,
        blocks: list[StrategyExtractedBlock],
        source_type: str,
        original_filename: str,
        storage_path: str,
        tags: list[str] | None,
        knowledge_type: str,
        document_id: str | None = None,
        parse_status: str = "success",
        parse_error: str = "",
        content_hash: str = "",
    ) -> tuple[StrategyDocument, list[StrategyKnowledgeChunk]]:
        normalized_type = _normalize_knowledge_type(knowledge_type)
        normalized_tags = [sanitize_text(tag).strip() for tag in tags or [] if sanitize_text(tag).strip()]
        if not normalized_tags and source_type == "text":
            normalized_tags = ["默认"]
        document = StrategyDocument(
            document_id=document_id or "kdoc_" + uuid4().hex,
            title=title,
            content=content,
            source_type=source_type,
            original_filename=original_filename,
            storage_path=storage_path,
            content_hash=content_hash or hashlib.sha256(content.encode("utf-8")).hexdigest(),
            tags=normalized_tags,
            knowledge_type=normalized_type,
            parse_status=parse_status,
            parse_error=parse_error,
        )
        for block in blocks:
            block.document_id = document.document_id
        chunks = _chunks_from_blocks(
            document_id=document.document_id,
            title=document.title,
            source_type=document.source_type,
            tags=document.tags,
            knowledge_type=document.knowledge_type,
            blocks=blocks,
        )
        saved = self.store.add_document(document, blocks, chunks)
        return saved, chunks


def _analysis_query(identity: ConversationIdentity, messages: list[Message], instruction: str, user_direction: str = "") -> str:
    recent = "\n".join(f"{message.sender_type.value}: {message.content}" for message in messages[-20:])
    weighted_direction = "\n".join([f"用户思路（高权重）: {user_direction}"] * 3) if user_direction else ""
    return "\n".join([identity.display_name, weighted_direction, instruction, recent])


def _reject_polluted_knowledge_text(content: str, title: str = "") -> None:
    markers = _knowledge_pollution_markers(content)
    if len(markers) >= 2:
        sample = "、".join(markers[:5])
        raise ValueError(f"疑似把检索结果/前端页面/调试日志当成知识入库，已拒绝保存：{title or '文本知识'}。命中痕迹：{sample}")


def _knowledge_pollution_markers(content: str) -> list[str]:
    text = sanitize_text(content)
    patterns = [
        ("score 分数", r"\bscore\s+[-+]?\d+(?:\.\d+)?"),
        ("pdf 页码来源", r"\bpdf:page:\d+"),
        ("chunk 来源", r"\b(docx:paragraph|pptx:slide|text:block):\d+"),
        ("知识库命中标题", r"知识库命中|命中与来源预览|检索知识库"),
        ("联系人知识库 UI", r"联系人知识库开关|启用状态|Contact|Enabled"),
        ("前端标签 UI", r"回复策略、关系判断、回复内容、话术|类型\s*默认|标签\s*回复"),
        ("向量诊断", r"向量：|可用\s*\d+|跳过旧模型|向量命中"),
        ("系统操作文本", r"上传并建立索引|正在建立索引|重建索引|请选择文档"),
    ]
    markers: list[str] = []
    for label, pattern in patterns:
        if re.search(pattern, text, re.I):
            markers.append(label)
    return markers


def _source_type_from_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in {"pdf", "docx", "pptx", "txt", "md"}:
        return "text" if suffix in {"txt", "md"} else suffix
    return suffix or "binary"


def _parse_document_bytes(raw: bytes, filename: str, source_type: str) -> dict:
    try:
        if source_type == "docx":
            blocks = _parse_docx_blocks(raw)
        elif source_type == "pptx":
            blocks = _parse_pptx_blocks(raw)
        elif source_type == "pdf":
            blocks = _parse_pdf_blocks(raw)
        elif source_type == "text":
            text = raw.decode("utf-8", errors="replace")
            blocks = _blocks_from_text(text, "text")
        else:
            text = raw.decode("utf-8", errors="replace")
            blocks = _blocks_from_text(text, source_type)
        content = "\n\n".join(block.text for block in blocks if block.text.strip())
        if not content.strip():
            return {
                "content": "",
                "blocks": [],
                "parse_status": "failed",
                "parse_error": "未提取到文本内容；图片和扫描件当前不会 OCR。",
            }
        return {"content": content, "blocks": blocks, "parse_status": "success", "parse_error": ""}
    except Exception as exc:
        return {
            "content": "",
            "blocks": [],
            "parse_status": "failed",
            "parse_error": f"{filename} 文本解析失败: {exc}",
        }


def _blocks_from_text(text: str, source_type: str) -> list[StrategyExtractedBlock]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]
    return [
        StrategyExtractedBlock(
            document_id="",
            block_index=index,
            block_type="paragraph",
            text=paragraph,
            source_location=f"{source_type}:block:{index}",
        )
        for index, paragraph in enumerate(paragraphs, 1)
    ]


def _parse_docx_blocks(raw: bytes) -> list[StrategyExtractedBlock]:
    with ZipFile(_bytes_as_file(raw)) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    raw_paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
        text = sanitize_text("".join(texts)).strip()
        if text and not re.match(r"^第\s*\d+\s*页\s*共\s*\d+\s*页$", text):
            raw_paragraphs.append(text)
    merged = _merge_wrapped_lines(raw_paragraphs)
    return [
        StrategyExtractedBlock(
            document_id="",
            block_index=index,
            block_type=_block_type_for_text(text),
            text=text,
            source_location=f"docx:paragraph:{index}",
        )
        for index, text in enumerate(merged, 1)
    ]


def _parse_pptx_blocks(raw: bytes) -> list[StrategyExtractedBlock]:
    blocks: list[StrategyExtractedBlock] = []
    with ZipFile(_bytes_as_file(raw)) as archive:
        slide_names = sorted(
            name
            for name in archive.namelist()
            if re.match(r"ppt/slides/slide\d+\.xml$", name)
        )
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        for slide_index, name in enumerate(slide_names, 1):
            root = ET.fromstring(archive.read(name))
            texts = [node.text or "" for node in root.findall(".//a:t", ns)]
            text = sanitize_text("\n".join(part.strip() for part in texts if part.strip())).strip()
            if text:
                blocks.append(
                    StrategyExtractedBlock(
                        document_id="",
                        block_index=len(blocks) + 1,
                        block_type="slide_text",
                        text=text,
                        source_location=f"pptx:slide:{slide_index}",
                    )
                )
    return blocks


def _parse_pdf_blocks(raw: bytes) -> list[StrategyExtractedBlock]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf，无法解析 PDF 文本层；请安装依赖后重建索引。") from exc
    reader = PdfReader(_bytes_as_file(raw))
    blocks: list[StrategyExtractedBlock] = []
    page_texts = [sanitize_text(page.extract_text() or "").strip() for page in reader.pages]
    repeated_lines = _detect_repeated_pdf_lines(page_texts)
    for page_index, page_text in enumerate(page_texts, 1):
        text = _clean_pdf_page_text(page_text, repeated_lines)
        if not text:
            continue
        for block_type, block_text in _split_pdf_page_blocks(text):
            blocks.append(
                StrategyExtractedBlock(
                    document_id="",
                    block_index=len(blocks) + 1,
                    block_type=block_type,
                    text=block_text,
                    source_location=f"pdf:page:{page_index}",
                )
            )
    return blocks


def _detect_repeated_pdf_lines(page_texts: list[str]) -> set[str]:
    page_count = max(1, len(page_texts))
    line_pages: dict[str, set[int]] = {}
    for page_index, text in enumerate(page_texts, 1):
        seen_on_page: set[str] = set()
        for raw_line in text.splitlines():
            line = _normalize_pdf_noise_line(raw_line)
            if not line or len(line) < 4:
                continue
            seen_on_page.add(line)
        for line in seen_on_page:
            line_pages.setdefault(line, set()).add(page_index)
    threshold = max(3, min(8, math.ceil(page_count * 0.18)))
    return {line for line, pages in line_pages.items() if len(pages) >= threshold}


def _clean_pdf_page_text(text: str, repeated_lines: set[str]) -> str:
    cleaned: list[str] = []
    for raw_line in text.splitlines():
        line = sanitize_text(raw_line).strip()
        normalized = _normalize_pdf_noise_line(line)
        if not line or normalized in repeated_lines or _looks_pdf_noise_line(line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _normalize_pdf_noise_line(line: str) -> str:
    return re.sub(r"\s+", "", sanitize_text(line).strip().lower())


def _looks_pdf_noise_line(line: str) -> bool:
    compact = _normalize_pdf_noise_line(line)
    if not compact:
        return True
    if re.fullmatch(r"[\W_]+", compact):
        return True
    if re.fullmatch(r"\d+", compact):
        return True
    noise_patterns = [
        r"qq群",
        r"^qq[:：]?$",
        r"qq[:：]?\d{5,}",
        r"微信[:：]?",
        r"公众号",
        r"官方网址",
        r"https?://",
        r"www\.",
        r"版权所有",
        r"内部资料",
    ]
    return any(re.search(pattern, compact, re.I) for pattern in noise_patterns)


def _split_pdf_page_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        block_type = _block_type_for_text(line)
        if block_type == "heading":
            if current:
                blocks.extend(_paragraph_blocks_from_lines(current))
                current = []
            blocks.append(("heading", line))
            continue
        current.append(line)
    if current:
        blocks.extend(_paragraph_blocks_from_lines(current))
    return blocks


def _paragraph_blocks_from_lines(lines: list[str]) -> list[tuple[str, str]]:
    text = "\n".join(lines).strip()
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) <= 1:
        merged = _merge_wrapped_lines([line.strip() for line in lines if line.strip()])
        paragraphs = [part for part in merged if part]
    return [(_block_type_for_text(paragraph), paragraph) for paragraph in paragraphs]


def _bytes_as_file(raw: bytes):
    import io

    return io.BytesIO(raw)


def _merge_wrapped_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if merged and _looks_wrapped(merged[-1], line):
            merged[-1] = merged[-1] + line
        else:
            merged.append(line)
    return merged


def _looks_wrapped(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    if re.match(r"^([一二三四五六七八九十]+、|\d+[.、]|【)", current):
        return False
    if previous.endswith(("。", "！", "？", "；", ":", "：", "”", "」")):
        return False
    return len(previous) < 90


def _block_type_for_text(text: str) -> str:
    if re.match(r"^第[一二三四五六七八九十百零\d]+\s*[章节讲课篇][\s:：、-]*", text):
        return "heading"
    if re.match(r"^[一二三四五六七八九十]+、", text):
        return "heading"
    if re.match(r"^\d+[.、]", text):
        return "list_item"
    if re.match(r"^(男|女|我|她|他)[:：]", text):
        return "dialogue"
    return "paragraph"


def _chunks_from_blocks(
    document_id: str,
    title: str,
    source_type: str,
    tags: list[str],
    knowledge_type: str,
    blocks: list[StrategyExtractedBlock],
    max_chars: int = 700,
    overlap: int = 80,
) -> list[StrategyKnowledgeChunk]:
    chunks: list[StrategyKnowledgeChunk] = []
    current_text = ""
    current_locations: list[str] = []
    current_heading = ""
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.block_type == "heading":
            if current_text:
                chunks.append(
                    _make_chunk(
                        document_id,
                        title,
                        source_type,
                        tags,
                        knowledge_type,
                        current_text,
                        current_locations,
                        len(chunks) + 1,
                        current_heading,
                    )
                )
                current_text = ""
                current_locations = []
            current_heading = text
            current_text = text
            current_locations = [block.source_location]
            continue
        if len(text) > max_chars:
            if current_text:
                chunks.append(_make_chunk(document_id, title, source_type, tags, knowledge_type, current_text, current_locations, len(chunks) + 1, current_heading))
                current_text = ""
                current_locations = []
            for part in _split_chunks(text, max_chars=max_chars, overlap=overlap):
                chunk_text = f"{current_heading}\n\n{part}".strip() if current_heading else part
                chunks.append(_make_chunk(document_id, title, source_type, tags, knowledge_type, chunk_text, [block.source_location], len(chunks) + 1, current_heading))
            continue
        candidate = f"{current_text}\n\n{text}".strip() if current_text else text
        if len(candidate) > max_chars and current_text:
            chunks.append(_make_chunk(document_id, title, source_type, tags, knowledge_type, current_text, current_locations, len(chunks) + 1, current_heading))
            current_text = f"{current_heading}\n\n{text}".strip() if current_heading else text
            current_locations = [block.source_location]
        else:
            current_text = candidate
            current_locations.append(block.source_location)
    if current_text:
        chunks.append(_make_chunk(document_id, title, source_type, tags, knowledge_type, current_text, current_locations, len(chunks) + 1, current_heading))
    return chunks


def _make_chunk(
    document_id: str,
    title: str,
    source_type: str,
    tags: list[str],
    knowledge_type: str,
    text: str,
    locations: list[str],
    index: int,
    heading: str = "",
) -> StrategyKnowledgeChunk:
    chunk_title = f"{title} / {heading}" if heading and heading not in title else title
    return StrategyKnowledgeChunk(
        document_id=document_id,
        title=chunk_title,
        source_type=source_type,
        source_location=", ".join(locations[:3]),
        source_locations=locations,
        tags=list(tags),
        knowledge_type=knowledge_type,
        chunk_text=text.strip(),
        chunk_index=index,
    )


def _split_chunks(content: str, max_chars: int = 700, overlap: int = 80) -> list[str]:
    """Neutral fixed-window chunking.

    The system does not infer document structure or knowledge type here. For
    short content, the original text is stored as one chunk. Long content is
    split only to keep retrieval/model inputs bounded.
    """
    text = content.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    step = max(1, max_chars - overlap)
    while start < len(text):
        chunk = text[start : start + max_chars].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def _tokenize(text: str) -> list[str]:
    normalized = sanitize_text(text).lower()
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{1,2}", normalized)
    stopwords = {"的", "了", "和", "是", "我", "你", "他", "她", "它", "我们", "你们", "他们", "这个", "那个"}
    return [token for token in tokens if token not in stopwords and token.strip()]


def _lexical_score(query_terms: list[str], chunk: StrategyKnowledgeChunk) -> float:
    text_terms = _tokenize(" ".join([chunk.title, chunk.knowledge_type, " ".join(chunk.tags), chunk.chunk_text]))
    if not text_terms:
        return 0.0
    counts: dict[str, int] = {}
    for term in text_terms:
        counts[term] = counts.get(term, 0) + 1
    score = sum(math.log(1 + counts.get(term, 0)) for term in query_terms)
    if chunk.knowledge_type in {"strategy", "reply_material", "relationship", "risk_rule"}:
        score *= 1.08
    return round(score, 6)


def _chunk_embedding_text(chunk: StrategyKnowledgeChunk) -> str:
    return "\n".join(
        [
            chunk.title,
            chunk.knowledge_type,
            " ".join(chunk.tags),
            chunk.chunk_text,
            chunk.source_location,
        ]
    )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _copy_chunk_with_score(
    chunk: StrategyKnowledgeChunk,
    score: float,
    vector_score: float = 0.0,
    lexical_score: float = 0.0,
    score_source: str = "",
) -> StrategyKnowledgeChunk:
    return StrategyKnowledgeChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        title=chunk.title,
        source_type=chunk.source_type,
        source_location=chunk.source_location,
        source_locations=list(chunk.source_locations),
        tags=list(chunk.tags),
        knowledge_type=chunk.knowledge_type,
        enabled=chunk.enabled,
        chunk_text=chunk.chunk_text,
        chunk_index=chunk.chunk_index,
        score=score,
        vector_score=vector_score,
        lexical_score=lexical_score,
        score_source=score_source,
        created_at=chunk.created_at,
    )


def _normalize_knowledge_type(value: str) -> str:
    value = (value or "unknown").strip().lower()
    return value if value and value != "unknown" else "unlabeled"


def _analysis_system_prompt() -> str:
    return (
        "你是微信会话策略分析器，只做分析，不生成自动发送任务。\n"
        "你必须结合输入的聊天记录、用户分析要求、用户思路和知识库命中片段，输出 JSON object。\n"
        "用户思路代表用户此轮对话期望的方向，权重最高；除非它与聊天记录明显冲突，否则策略和候选回复都要优先贴合它。\n"
        "不要假设知识类型；知识库片段的标签只作为原始元数据。\n"
        "如果知识库片段与当前会话无关，要明确降低其影响。\n"
        "禁止输出发送指令、自动执行动作或声称已修改配置。"
    )


def _analysis_user_prompt(
    identity: ConversationIdentity,
    messages: list[Message],
    instruction: str,
    knowledge: list[StrategyKnowledgeChunk],
    user_direction: str = "",
) -> str:
    payload = {
        "output_schema": {
            "intent": "string，对方当前意图",
            "needs": ["string，对方需求"],
            "relationship_signal": "string，关系/边界/亲疏信号",
            "risks": ["string，风险和不该做的事"],
            "suggested_strategy": "string，受知识库影响后的回复策略建议",
            "reply_examples": ["string，只是候选示例，不发送"],
        },
        "conversation": asdict(identity),
        "instruction": instruction,
        "user_direction_high_weight": user_direction,
        "recent_messages": [
            {
                "sender_type": message.sender_type.value,
                "sender_name": message.sender_name,
                "message_type": message.message_type.value,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages
        ],
        "matched_knowledge": [_knowledge_prompt_item(chunk) for chunk in knowledge],
        "constraints": [
            "只输出 JSON object。",
            "用户思路是本轮最高权重输入；建议策略和候选回复必须优先服务这个方向。",
            "如果用户思路与聊天记录明显冲突，要在 risks 或 suggested_strategy 里说明冲突，而不是盲目执行。",
            "reply_examples 只是建议，不能表示已经发送。",
            "不要把知识库片段当作绝对规则，除非它与当前聊天明显相关。",
            "不知道就写不确定，不要编造私人背景。",
        ],
    }
    return json.dumps(sanitize_jsonable(payload), ensure_ascii=False)


def _knowledge_prompt_item(chunk: StrategyKnowledgeChunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "title": chunk.title,
        "source_type": chunk.source_type,
        "tags": chunk.tags,
        "knowledge_type": chunk.knowledge_type,
        "score": chunk.score,
        "text": chunk.chunk_text,
    }


def _coerce_str_list(value) -> list[str]:
    if isinstance(value, str):
        return [sanitize_text(value).strip()] if sanitize_text(value).strip() else []
    if not isinstance(value, list):
        return []
    return [sanitize_text(str(item)).strip() for item in value if sanitize_text(str(item)).strip()]


def _document_to_dict(document: StrategyDocument) -> dict:
    return {
        "document_id": document.document_id,
        "title": document.title,
        "source_type": document.source_type,
        "original_filename": document.original_filename,
        "storage_path": document.storage_path,
        "content_hash": document.content_hash,
        "tags": document.tags,
        "knowledge_type": document.knowledge_type,
        "status": document.status,
        "parse_status": document.parse_status,
        "parse_error": document.parse_error,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _chunk_to_dict(chunk: StrategyKnowledgeChunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "title": chunk.title,
        "source_type": chunk.source_type,
        "source_location": chunk.source_location,
        "source_locations": chunk.source_locations,
        "tags": chunk.tags,
        "knowledge_type": chunk.knowledge_type,
        "enabled": chunk.enabled,
        "chunk_text": chunk.chunk_text,
        "chunk_index": chunk.chunk_index,
        "score": chunk.score,
        "vector_score": chunk.vector_score,
        "lexical_score": chunk.lexical_score,
        "score_source": chunk.score_source,
        "created_at": chunk.created_at.isoformat(),
    }
