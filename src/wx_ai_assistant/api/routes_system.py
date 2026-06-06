from fastapi import APIRouter, Request
from dataclasses import asdict

from wx_ai_assistant.core.response import ok, fail

router = APIRouter(prefix="/system", tags=["system"])


@router.post("/initialize")
def initialize(request: Request):
    app_service = request.app.state.app_service
    command = app_service.request_runtime_command("initialize")
    try:
        data = asdict(command)
    except TypeError:
        data = command
    return ok(data, "微信自检命令已入队")


@router.get("/status")
def status(request: Request):
    app_service = request.app.state.app_service
    runtime = app_service.runtime_snapshot()
    driver_status = runtime.get("last_driver_status")
    if not driver_status:
        return fail("微信运行 Worker 尚未完成自检", {"runtime_worker": runtime})
    return ok({"driver_status": driver_status, "runtime_worker": runtime})


@router.get("/current-conversation")
def current_conversation(request: Request):
    app_service = request.app.state.app_service
    runtime = app_service.runtime_snapshot()
    return ok(runtime.get("last_current_conversation"))


@router.get("/diagnostics")
def diagnostics(request: Request):
    app_service = request.app.state.app_service
    settings = request.app.state.settings
    data = app_service.diagnostics_snapshot()
    data["settings"] = {
        "driver_mode": settings.driver_mode,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "ai_mode": settings.ai_mode,
        "ai_model": settings.ai_model,
        "ai_base_url": settings.ai_base_url,
        "ai_api_key_configured": bool(settings.ai_api_key),
        "auto_send_enabled": settings.auto_send_enabled,
        "ai_core_prompt_path": str(settings.ai_core_prompt_path),
        "ai_prompt_path": str(settings.ai_prompt_path),
        "ai_style_path": str(settings.ai_style_path),
        "ai_proactive_mode": settings.ai_proactive_mode,
        "ai_max_messages_per_turn": settings.ai_max_messages_per_turn,
        "ai_strict_turn_json": settings.ai_strict_turn_json,
        "ai_turn_quiet_seconds": settings.ai_turn_quiet_seconds,
        "ai_duplicate_guard_seconds": settings.ai_duplicate_guard_seconds,
        "diagnostics_context_chars": settings.diagnostics_context_chars,
        "vision_ai_enabled": settings.vision_ai_enabled,
        "vision_ai_base_url": settings.vision_ai_base_url,
        "vision_ai_api_key_configured": bool(settings.vision_ai_api_key),
        "vision_ai_model": settings.vision_ai_model,
        "speech_ai_enabled": settings.speech_ai_enabled,
        "speech_ai_base_url": settings.speech_ai_base_url,
        "speech_ai_api_key_configured": bool(settings.speech_ai_api_key),
        "speech_ai_model": settings.speech_ai_model,
        "db_path": str(settings.db_path),
        "history_db_path": str(settings.history_db_path),
        "wechat_locators": str(settings.wechat_locators),
    }
    return ok(data)
