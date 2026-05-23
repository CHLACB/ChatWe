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
