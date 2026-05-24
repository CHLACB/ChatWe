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
    proactive_mode: str | None = None
    max_messages_per_turn: int | None = None
    turn_quiet_seconds: float | None = None
    duplicate_guard_seconds: float | None = None
    core_prompt: str | None = None
    turn_prompt: str | None = None
    style_prompt: str | None = None
    contact_policies_json: str | None = None
    conversation_profiles_json: str | None = None
