from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Request

from wx_ai_assistant.api.schemas import SendTextRequest
from wx_ai_assistant.core.response import ok
from wx_ai_assistant.domain.enums import SendTaskStatus

router = APIRouter(prefix="/send", tags=["send"])


@router.post("/text")
def send_text(payload: SendTextRequest, request: Request):
    app_service = request.app.state.app_service
    try:
        task = app_service.send_text_manually(payload.conversation_id, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(asdict(task), "已加入发送队列")


@router.get("/tasks")
def list_tasks(
    request: Request,
    conversation_id: str | None = None,
    status: SendTaskStatus | None = None,
    limit: int = 50,
):
    app_service = request.app.state.app_service
    tasks = app_service.list_send_tasks(conversation_id=conversation_id, status=status, limit=limit)
    return ok([asdict(t) for t in tasks])


@router.get("/tasks/{send_task_id}")
def get_task(send_task_id: str, request: Request):
    app_service = request.app.state.app_service
    task = app_service.get_send_task(send_task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="发送任务不存在")
    return ok(asdict(task))


@router.post("/tasks/{send_task_id}/retry")
def retry_task(send_task_id: str, request: Request):
    app_service = request.app.state.app_service
    try:
        command = app_service.request_retry_send_task(send_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        data = asdict(command)
    except TypeError:
        data = command
    return ok(data, "重试发送命令已入队")
