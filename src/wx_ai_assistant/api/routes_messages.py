from dataclasses import asdict
from fastapi import APIRouter, Request

from wx_ai_assistant.api.schemas import MockTextMessageRequest
from wx_ai_assistant.core.response import ok

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/{conversation_id}")
def recent_messages(conversation_id: str, request: Request, limit: int = 50):
    app_service = request.app.state.app_service
    messages = app_service.list_recent_messages(conversation_id, limit)
    return ok([asdict(m) for m in messages])


@router.post("/mock/text")
def create_mock_text_message(payload: MockTextMessageRequest, request: Request):
    app_service = request.app.state.app_service
    message = app_service.create_mock_text_message(
        conversation_id=payload.conversation_id,
        content=payload.content,
        sender_name=payload.sender_name,
    )
    return ok(asdict(message), "mock 文本消息已进入主链路")
