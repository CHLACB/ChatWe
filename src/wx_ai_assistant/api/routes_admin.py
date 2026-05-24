from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from wx_ai_assistant.api.schemas import AiConfigUpdateRequest
from wx_ai_assistant.core.response import ok

router = APIRouter(prefix="/admin-api", tags=["admin"])


@router.get("/overview")
def overview(request: Request, limit: int = 20):
    app_service = request.app.state.app_service
    diagnostics = app_service.diagnostics_snapshot()
    targets = app_service.list_listen_targets()
    target_ids = [target.conversation.conversation_id for target in targets]
    messages_by_target = {
        conversation_id: [
            _message_to_dict(message)
            for message in app_service.list_recent_messages(conversation_id, limit=limit)
        ]
        for conversation_id in target_ids
    }
    send_tasks = [asdict(task) for task in app_service.list_send_tasks(limit=50)]
    decisions = app_service.list_ai_decision_logs(limit=20)
    return ok(
        {
            "diagnostics": diagnostics,
            "targets": [asdict(target) for target in targets],
            "messages_by_target": messages_by_target,
            "send_tasks": send_tasks,
            "ai_decisions": decisions,
        }
    )


@router.get("/ai-decisions")
def ai_decisions(
    request: Request,
    conversation_id: str | None = None,
    run_id: str | None = None,
    limit: int = 20,
):
    app_service = request.app.state.app_service
    return ok(app_service.list_ai_decision_logs(conversation_id=conversation_id, run_id=run_id, limit=limit))


@router.post("/conversations/{conversation_id}/clear-memory")
def clear_memory(conversation_id: str, request: Request):
    app_service = request.app.state.app_service
    if app_service.repo.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {conversation_id}")
    result = app_service.clear_conversation_memory(conversation_id)
    return ok(result, "已清除本地记忆。微信本机聊天记录不会被删除。")


@router.get("/config")
def get_config(request: Request):
    settings = request.app.state.settings
    return ok(
        {
            "ai_mode": settings.ai_mode,
            "base_url": settings.ai_base_url,
            "api_key_configured": bool(settings.ai_api_key),
            "model": settings.ai_model,
            "temperature": settings.ai_temperature,
            "max_tokens": settings.ai_max_tokens,
            "timeout_seconds": settings.ai_timeout_seconds,
            "proactive_mode": settings.ai_proactive_mode,
            "max_messages_per_turn": settings.ai_max_messages_per_turn,
            "turn_quiet_seconds": settings.ai_turn_quiet_seconds,
            "duplicate_guard_seconds": settings.ai_duplicate_guard_seconds,
            "paths": {
                "ai_config": str(settings.ai_config),
                "core_prompt": str(settings.ai_core_prompt_path),
                "turn_prompt": str(settings.ai_prompt_path),
                "style_prompt": str(settings.ai_style_path),
                "contact_policies": str(settings.contact_policies_path),
                "conversation_profiles": str(settings.conversation_profiles_path),
            },
            "core_prompt": _read_text(settings.ai_core_prompt_path),
            "turn_prompt": _read_text(settings.ai_prompt_path),
            "style_prompt": _read_text(settings.ai_style_path),
            "contact_policies_json": _read_json_text(settings.contact_policies_path),
            "conversation_profiles_json": _read_json_text(settings.conversation_profiles_path),
        }
    )


@router.post("/config")
def update_config(payload: AiConfigUpdateRequest, request: Request):
    settings = request.app.state.settings
    updates: dict[str, str] = {}
    _set(updates, "APP_AI_BASE_URL", payload.base_url)
    _set(updates, "APP_AI_MODEL", payload.model)
    _set(updates, "APP_AI_TEMPERATURE", payload.temperature)
    _set(updates, "APP_AI_MAX_TOKENS", payload.max_tokens)
    _set(updates, "APP_AI_TIMEOUT_SECONDS", payload.timeout_seconds)
    _set(updates, "APP_AI_PROACTIVE_MODE", payload.proactive_mode)
    _set(updates, "APP_AI_MAX_MESSAGES_PER_TURN", payload.max_messages_per_turn)
    _set(updates, "APP_AI_TURN_QUIET_SECONDS", payload.turn_quiet_seconds)
    _set(updates, "APP_AI_DUPLICATE_GUARD_SECONDS", payload.duplicate_guard_seconds)
    if payload.api_key:
        _set(updates, "APP_AI_API_KEY", payload.api_key)
    if updates:
        _merge_env_file(settings.ai_config, updates)
    _write_optional_text(settings.ai_core_prompt_path, payload.core_prompt)
    _write_optional_text(settings.ai_prompt_path, payload.turn_prompt)
    _write_optional_text(settings.ai_style_path, payload.style_prompt)
    _write_optional_json(settings.contact_policies_path, payload.contact_policies_json)
    _write_optional_json(settings.conversation_profiles_path, payload.conversation_profiles_json)
    return ok({"restart_required": True}, "配置已保存，重启服务后生效。")


def _message_to_dict(message):
    return {
        "message_id": message.message_id,
        "conversation_id": message.conversation_id,
        "sender_type": message.sender_type.value,
        "message_type": message.message_type.value,
        "content": message.content,
        "sender_name": message.sender_name,
        "created_at": message.created_at.isoformat(),
        "received_at": message.received_at.isoformat(),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


def _read_json_text(path: Path) -> str:
    if path.exists():
        return _read_text(path)
    example = path.with_name(path.name.replace(".local.", ".local.example."))
    return _read_text(example)


def _write_optional_text(path: Path, value: str | None) -> None:
    if value is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_optional_json(path: Path, value: str | None) -> None:
    if value is None:
        return
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{path.name} 不是合法 JSON: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")


def _set(updates: dict[str, str], key: str, value) -> None:
    if value is not None:
        updates[key] = str(value)


def _merge_env_file(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            current[key.strip()] = value.strip()
    current.update(updates)
    lines = [f"{key}={value}" for key, value in current.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
