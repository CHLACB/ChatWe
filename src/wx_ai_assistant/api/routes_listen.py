from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Request

from wx_ai_assistant.api.schemas import AddListenTargetRequest
from wx_ai_assistant.core.response import ok

router = APIRouter(prefix="/listen", tags=["listen"])


@router.post("/targets")
def add_target(payload: AddListenTargetRequest, request: Request):
    app_service = request.app.state.app_service
    try:
        target = app_service.add_listen_target(
            display_name=payload.display_name,
            conversation_type=payload.conversation_type,
            remark_name=payload.remark_name,
            local_id=payload.local_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(asdict(target), "监听对象已创建，默认未监听")


@router.get("/targets")
def list_targets(request: Request):
    app_service = request.app.state.app_service
    targets = app_service.list_listen_targets()
    return ok([asdict(t) for t in targets])


@router.post("/targets/{conversation_id}/start")
def start_target(conversation_id: str, request: Request):
    app_service = request.app.state.app_service
    command = app_service.request_start_listen_target(conversation_id)
    return ok(_command_or_result(command, {"conversation_id": conversation_id}), "启动监听命令已入队")


@router.post("/targets/{conversation_id}/stop")
def stop_target(conversation_id: str, request: Request):
    app_service = request.app.state.app_service
    app_service.stop_listen_target(conversation_id, "manual stop")
    return ok({"conversation_id": conversation_id}, "已停止监听")


@router.delete("/targets/{conversation_id}")
def delete_target(conversation_id: str, request: Request):
    app_service = request.app.state.app_service
    deleted = app_service.delete_listen_target(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"监听对象不存在: {conversation_id}")
    return ok({"conversation_id": conversation_id}, "已删除监听对象")


@router.post("/poll-once")
def poll_once(request: Request):
    app_service = request.app.state.app_service
    command = app_service.request_poll_listeners_once()
    return ok(_command_or_result(command, {}), "监听轮询命令已入队")


def _command_or_result(value, fallback: dict):
    try:
        return asdict(value)
    except TypeError:
        return value if isinstance(value, dict) else fallback
