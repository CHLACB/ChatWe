from fastapi import APIRouter, Request
from dataclasses import asdict

from wx_ai_assistant.core.response import ok, fail

router = APIRouter(prefix="/system", tags=["system"])


@router.post("/initialize")
def initialize(request: Request):
    app_service = request.app.state.app_service
    status = app_service.initialize()
    return ok(status.__dict__) if status.ok else fail(status.message, status.__dict__)


@router.get("/status")
def status(request: Request):
    app_service = request.app.state.app_service
    status = app_service.status()
    return ok(status.__dict__) if status.ok else fail(status.message, status.__dict__)


@router.get("/current-conversation")
def current_conversation(request: Request):
    app_service = request.app.state.app_service
    current = app_service.current_conversation()
    return ok(asdict(current) if current else None)
