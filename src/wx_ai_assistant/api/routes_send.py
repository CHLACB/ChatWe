from dataclasses import asdict
from fastapi import APIRouter, Request

from wx_ai_assistant.api.schemas import SendTextRequest
from wx_ai_assistant.core.response import ok

router = APIRouter(prefix="/send", tags=["send"])


@router.post("/text")
def send_text(payload: SendTextRequest, request: Request):
    app_service = request.app.state.app_service
    task = app_service.send_text_manually(payload.conversation_id, payload.content)
    return ok(asdict(task), "已加入发送队列")
