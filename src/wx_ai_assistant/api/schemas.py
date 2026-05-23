from pydantic import BaseModel, Field

from wx_ai_assistant.domain.enums import ConversationType


class AddListenTargetRequest(BaseModel):
    display_name: str = Field(min_length=1)
    conversation_type: ConversationType
    remark_name: str | None = None
    local_id: str | None = None


class SendTextRequest(BaseModel):
    conversation_id: str
    content: str = Field(min_length=1)


class MockTextMessageRequest(BaseModel):
    conversation_id: str
    content: str = Field(min_length=1)
    sender_name: str = "other"
