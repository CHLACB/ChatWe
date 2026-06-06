from pydantic import BaseModel, Field

from wx_ai_assistant.domain.enums import ConversationType, SendTaskStatus


class AddListenTargetRequest(BaseModel):
    display_name: str = Field(min_length=1)
    conversation_type: ConversationType
    remark_name: str | None = None
    local_id: str | None = None


class SendTextRequest(BaseModel):
    conversation_id: str
    content: str = Field(min_length=1)


class SendTaskQuery(BaseModel):
    conversation_id: str | None = None
    status: SendTaskStatus | None = None
    limit: int = Field(default=50, ge=1, le=200)


class MockTextMessageRequest(BaseModel):
    conversation_id: str
    content: str = Field(min_length=1)
    sender_name: str = "other"


class AiConfigUpdateRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    extra_body: str | None = None
    auto_send_enabled: bool | None = None
    proactive_mode: str | None = None
    max_messages_per_turn: int | None = None
    turn_quiet_seconds: float | None = None
    duplicate_guard_seconds: float | None = None
    vision_enabled: bool | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None
    vision_model: str | None = None
    vision_temperature: float | None = None
    vision_max_tokens: int | None = None
    vision_timeout_seconds: float | None = None
    vision_system_prompt: str | None = None
    vision_extra_body: str | None = None
    speech_enabled: bool | None = None
    speech_base_url: str | None = None
    speech_api_key: str | None = None
    speech_model: str | None = None
    speech_language: str | None = None
    speech_prompt: str | None = None
    speech_timeout_seconds: float | None = None
    core_prompt: str | None = None
    prompt_extensions_json: str | None = None
    langgraph_nodes_json: str | None = None


class ProactivePreviewRequest(BaseModel):
    instruction: str | None = None
