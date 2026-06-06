from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from wx_ai_assistant.core.response import ok


router = APIRouter(prefix="/strategy-analysis", tags=["strategy-analysis"])


class StrategyDocumentTextRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_type: str = "text"
    tags: list[str] = Field(default_factory=list)
    knowledge_type: str = "unknown"


class StrategyDocumentUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    knowledge_type: str = "unknown"


class ContactKnowledgeSettingsRequest(BaseModel):
    enabled: bool = False
    document_ids: list[str] | None = None
    tag_filters: list[str] | None = None


class StrategyKnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=6, ge=1, le=20)
    knowledge_type: str | None = None
    document_ids: list[str] | None = None


class ConversationStrategyAnalysisRequest(BaseModel):
    instruction: str | None = None
    user_direction: str | None = None
    message_limit: int = Field(default=80, ge=1, le=500)
    knowledge_limit: int = Field(default=6, ge=0, le=20)


@router.post("/documents/text")
def add_text_document(payload: StrategyDocumentTextRequest, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(
            service.add_text_document(
                title=payload.title,
                content=payload.content,
                source_type=payload.source_type,
                tags=payload.tags,
                knowledge_type=payload.knowledge_type,
            ),
            "策略分析知识文档已入库。",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/documents/upload")
def upload_document(payload: StrategyDocumentUploadRequest, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(
            service.add_uploaded_document(
                filename=payload.filename,
                content_base64=payload.content_base64,
                title=payload.title,
                tags=payload.tags,
                knowledge_type=payload.knowledge_type,
            ),
            "知识文档已上传并建立索引。",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/documents")
def list_documents(request: Request, limit: int = 50):
    service = request.app.state.strategy_analysis_service
    return ok(service.list_documents(limit=limit))


@router.get("/documents/{document_id}")
def get_document(document_id: str, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(service.get_document(document_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/enable")
def enable_document(document_id: str, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(service.set_document_enabled(document_id, True), "文档已启用。")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/disable")
def disable_document(document_id: str, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(service.set_document_enabled(document_id, False), "文档已禁用。")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(service.delete_document(document_id), "文档已删除。")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/rebuild-index")
def rebuild_document_index(document_id: str, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(service.rebuild_document_index(document_id), "文档索引已重建。")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/knowledge/search")
def search_knowledge(payload: StrategyKnowledgeSearchRequest, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(
            service.search_knowledge(
                payload.query,
                limit=payload.limit,
                knowledge_type=payload.knowledge_type,
                document_ids=payload.document_ids,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/contacts/{conversation_id}/settings")
def get_contact_knowledge_settings(conversation_id: str, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(service.get_contact_knowledge_settings(conversation_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/contacts/{conversation_id}/settings")
def set_contact_knowledge_settings(conversation_id: str, payload: ContactKnowledgeSettingsRequest, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        return ok(
            service.set_contact_knowledge_settings(
                conversation_id,
                enabled=payload.enabled,
                document_ids=payload.document_ids,
                tag_filters=payload.tag_filters,
            ),
            "联系人知识库设置已保存。",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/conversations/{conversation_id}/analyze")
def analyze_conversation(conversation_id: str, payload: ConversationStrategyAnalysisRequest, request: Request):
    service = request.app.state.strategy_analysis_service
    try:
        report = service.analyze_conversation(
            conversation_id=conversation_id,
            instruction=payload.instruction or "",
            user_direction=payload.user_direction or "",
            message_limit=payload.message_limit,
            knowledge_limit=payload.knowledge_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "不存在" in str(exc) else 400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(asdict(report), "策略分析完成；未发送任何消息。")
