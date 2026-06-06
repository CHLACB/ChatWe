from __future__ import annotations

from typing import Protocol

from wx_ai_assistant.domain.enums import MessageType


class VisionGateway(Protocol):
    """Boundary for image/sticker understanding.

    This is deliberately separate from AiGateway. The chat model decides how to
    reply; the vision model only turns media into a concise text description.
    """

    def describe_image(self, image_path: str, message_type: MessageType, prompt: str = "") -> str:
        ...
