from dataclasses import dataclass
from typing import Protocol, Optional

from wx_ai_assistant.domain.models import ConversationIdentity, Message


@dataclass
class DriverStatus:
    ok: bool
    mode: str
    message: str
    details: dict | None = None


@dataclass
class SendResult:
    ok: bool
    message: str = ""
    details: dict | None = None


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int | None = None
    visible: bool | None = None
    minimized: bool | None = None


@dataclass
class ControlNode:
    name: str
    class_name: str
    control_type: str
    automation_id: str
    bounding_rectangle: str
    depth: int
    children_count: int


class WechatDriver(Protocol):
    """Boundary for all WeChat client operations.

    Real implementations must not guess controls. They should either use local locator
    config or return a clear DriverNotConfiguredError.
    """

    def initialize(self) -> DriverStatus:
        ...

    def status(self) -> DriverStatus:
        ...

    def switch_conversation(self, identity: ConversationIdentity) -> DriverStatus:
        ...

    def get_current_conversation(self) -> Optional[ConversationIdentity]:
        ...

    def read_visible_text_messages(self, identity: ConversationIdentity) -> list[Message]:
        ...

    def send_text(self, identity: ConversationIdentity, content: str) -> SendResult:
        ...
