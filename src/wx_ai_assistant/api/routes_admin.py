from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from wx_ai_assistant.api.schemas import AiConfigUpdateRequest, ProactivePreviewRequest
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


@router.post("/conversations/{conversation_id}/proactive-preview")
def proactive_preview(conversation_id: str, payload: ProactivePreviewRequest, request: Request):
    app_service = request.app.state.app_service
    if app_service.repo.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {conversation_id}")
    try:
        return ok(app_service.preview_proactive_message(conversation_id, payload.instruction or ""))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/conversations/{conversation_id}/proactive-send")
def proactive_send(conversation_id: str, payload: ProactivePreviewRequest, request: Request):
    app_service = request.app.state.app_service
    if app_service.repo.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {conversation_id}")
    try:
        return ok(app_service.queue_proactive_message(conversation_id, payload.instruction or ""), "主动触达判断完成，允许发送的消息已入队。")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
            "extra_body": settings.ai_extra_body,
            "auto_send_enabled": settings.auto_send_enabled,
            "proactive_mode": settings.ai_proactive_mode,
            "max_messages_per_turn": settings.ai_max_messages_per_turn,
            "turn_quiet_seconds": settings.ai_turn_quiet_seconds,
            "duplicate_guard_seconds": settings.ai_duplicate_guard_seconds,
            "vision_enabled": settings.vision_ai_enabled,
            "vision_base_url": settings.vision_ai_base_url,
            "vision_api_key_configured": bool(settings.vision_ai_api_key),
            "vision_model": settings.vision_ai_model,
            "vision_temperature": settings.vision_ai_temperature,
            "vision_max_tokens": settings.vision_ai_max_tokens,
            "vision_timeout_seconds": settings.vision_ai_timeout_seconds,
            "vision_system_prompt": settings.vision_ai_system_prompt,
            "vision_extra_body": settings.vision_ai_extra_body,
            "speech_enabled": settings.speech_ai_enabled,
            "speech_base_url": settings.speech_ai_base_url,
            "speech_api_key_configured": bool(settings.speech_ai_api_key),
            "speech_model": settings.speech_ai_model,
            "speech_language": settings.speech_ai_language,
            "speech_prompt": settings.speech_ai_prompt,
            "speech_timeout_seconds": settings.speech_ai_timeout_seconds,
            "paths": {
                "ai_config": str(settings.ai_config),
                "core_prompt": str(settings.ai_core_prompt_path),
                "prompt_extensions": str(settings.ai_extensions_path),
                "langgraph_nodes": str(settings.langgraph_nodes_path),
            },
            "core_prompt": _read_text(settings.ai_core_prompt_path),
            "prompt_extensions_json": _read_json_text(settings.ai_extensions_path),
            "langgraph_nodes_json": _read_json_text(settings.langgraph_nodes_path, fallback_empty_object=True),
        }
    )


@router.post("/config")
def update_config(payload: AiConfigUpdateRequest, request: Request):
    settings = request.app.state.settings
    updates: dict[str, str] = {}
    _validate_json_object_text(payload.extra_body, "APP_AI_EXTRA_BODY")
    _validate_json_object_text(payload.vision_extra_body, "APP_VISION_AI_EXTRA_BODY")
    _set(updates, "APP_AI_BASE_URL", payload.base_url)
    _set(updates, "APP_AI_MODEL", payload.model)
    _set(updates, "APP_AI_TEMPERATURE", payload.temperature)
    _set(updates, "APP_AI_MAX_TOKENS", payload.max_tokens)
    _set(updates, "APP_AI_TIMEOUT_SECONDS", payload.timeout_seconds)
    _set(updates, "APP_AI_EXTRA_BODY", payload.extra_body)
    if payload.auto_send_enabled is not None:
        _set(updates, "APP_AUTO_SEND_ENABLED", "true" if payload.auto_send_enabled else "false")
    _set(updates, "APP_AI_PROACTIVE_MODE", payload.proactive_mode)
    _set(updates, "APP_AI_MAX_MESSAGES_PER_TURN", payload.max_messages_per_turn)
    _set(updates, "APP_AI_TURN_QUIET_SECONDS", payload.turn_quiet_seconds)
    _set(updates, "APP_AI_DUPLICATE_GUARD_SECONDS", payload.duplicate_guard_seconds)
    if payload.vision_enabled is not None:
        _set(updates, "APP_VISION_AI_ENABLED", "true" if payload.vision_enabled else "false")
    _set(updates, "APP_VISION_AI_BASE_URL", payload.vision_base_url)
    _set(updates, "APP_VISION_AI_MODEL", payload.vision_model)
    _set(updates, "APP_VISION_AI_TEMPERATURE", payload.vision_temperature)
    _set(updates, "APP_VISION_AI_MAX_TOKENS", payload.vision_max_tokens)
    _set(updates, "APP_VISION_AI_TIMEOUT_SECONDS", payload.vision_timeout_seconds)
    _set(updates, "APP_VISION_AI_SYSTEM_PROMPT", payload.vision_system_prompt)
    _set(updates, "APP_VISION_AI_EXTRA_BODY", payload.vision_extra_body)
    if payload.speech_enabled is not None:
        _set(updates, "APP_SPEECH_AI_ENABLED", "true" if payload.speech_enabled else "false")
    _set(updates, "APP_SPEECH_AI_BASE_URL", payload.speech_base_url)
    _set(updates, "APP_SPEECH_AI_MODEL", payload.speech_model)
    _set(updates, "APP_SPEECH_AI_LANGUAGE", payload.speech_language)
    _set(updates, "APP_SPEECH_AI_PROMPT", payload.speech_prompt)
    _set(updates, "APP_SPEECH_AI_TIMEOUT_SECONDS", payload.speech_timeout_seconds)
    if payload.api_key:
        _set(updates, "APP_AI_API_KEY", payload.api_key)
    if payload.vision_api_key:
        _set(updates, "APP_VISION_AI_API_KEY", payload.vision_api_key)
    if payload.speech_api_key:
        _set(updates, "APP_SPEECH_AI_API_KEY", payload.speech_api_key)
    if updates:
        _merge_env_file(settings.ai_config, updates)
    _write_optional_text(settings.ai_core_prompt_path, payload.core_prompt)
    _write_optional_json(settings.ai_extensions_path, payload.prompt_extensions_json)
    _write_optional_json(settings.langgraph_nodes_path, payload.langgraph_nodes_json)
    return ok({"restart_required": True}, "配置已保存，重启服务后生效。")


def _message_to_dict(message):
    return {
        "message_id": message.message_id,
        "conversation_id": message.conversation_id,
        "sender_type": message.sender_type.value,
        "message_type": message.message_type.value,
        "content": message.content,
        "sender_name": message.sender_name,
        "media_path": message.media_path,
        "media_mime_type": message.media_mime_type,
        "media_description": message.media_description,
        "created_at": message.created_at.isoformat(),
        "received_at": message.received_at.isoformat(),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        return ""


def _read_json_text(path: Path, fallback_empty_object: bool = False) -> str:
    if path.exists():
        text = _read_text(path)
        if not fallback_empty_object:
            return text
        try:
            parsed = json.loads(text or "{}")
        except json.JSONDecodeError:
            return text
        if parsed != {}:
            return text
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


def _validate_json_object_text(value: str | None, field_name: str) -> None:
    if value is None or not value.strip():
        return
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 不是合法 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} 必须是 JSON object")


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



