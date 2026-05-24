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


@router.get("/diagnostics")
def diagnostics(request: Request):
    app_service = request.app.state.app_service
    settings = request.app.state.settings
    data = app_service.diagnostics_snapshot()
    data["settings"] = {
        "driver_mode": settings.driver_mode,
        "ai_mode": settings.ai_mode,
        "ai_model": settings.ai_model,
        "ai_base_url": settings.ai_base_url,
        "ai_api_key_configured": bool(settings.ai_api_key),
        "ai_core_prompt_path": str(settings.ai_core_prompt_path),
        "ai_prompt_path": str(settings.ai_prompt_path),
        "ai_style_path": str(settings.ai_style_path),
        "ai_proactive_mode": settings.ai_proactive_mode,
        "ai_max_messages_per_turn": settings.ai_max_messages_per_turn,
        "ai_strict_turn_json": settings.ai_strict_turn_json,
        "ai_turn_quiet_seconds": settings.ai_turn_quiet_seconds,
        "ai_duplicate_guard_seconds": settings.ai_duplicate_guard_seconds,
        "diagnostics_context_chars": settings.diagnostics_context_chars,
        "contact_policies_path": str(settings.contact_policies_path),
        "db_path": str(settings.db_path),
        "history_db_path": str(settings.history_db_path),
        "wechat_locators": str(settings.wechat_locators),
    }
    return ok(data)
