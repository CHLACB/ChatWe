from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.domain.enums import ConversationType  # noqa: E402
from wx_ai_assistant.domain.models import ConversationIdentity  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def line(status: str, name: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"{status:4} {name}{suffix}")


def describe(control: object) -> str:
    return (
        f"name={getattr(control, 'Name', '')!r} "
        f"type={getattr(control, 'ControlTypeName', '')!r} "
        f"rect={getattr(control, 'BoundingRectangle', '')!r}"
    )


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "文件传输助手"
    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    failed = False
    for key in ["navigation_avatar", "search_box", "conversation_list", "chat_title", "message_list", "input_box", "send_button"]:
        try:
            control = driver._locate_required(key)
            line("OK", key, describe(control))
        except Exception as exc:
            failed = True
            line("FAIL", key, str(exc))

    try:
        search_box = driver._locate_required("search_box")
        focused = driver._focus_search_box_with_hotkey(search_box)
        if focused is not None:
            line("OK", "ctrl_f_focus", describe(focused))
        else:
            failed = True
            line("FAIL", "ctrl_f_focus", describe(focused) if focused else "focused=None")
    except Exception as exc:
        failed = True
        line("FAIL", "ctrl_f_focus", str(exc))

    identity = ConversationIdentity(
        conversation_id="selfcheck_target",
        conversation_type=ConversationType.FRIEND,
        display_name=target,
        remark_name=target,
        local_id=target,
    )
    switch_status = driver.switch_conversation(identity)
    if switch_status.ok:
        line("OK", "switch_conversation", switch_status.message)
    else:
        failed = True
        line("FAIL", "switch_conversation", switch_status.message)

    current = driver.get_current_conversation()
    line("INFO", "current_conversation", repr(current))

    try:
        messages = driver.read_visible_text_messages(identity)
        line("OK", "read_visible_messages", f"count={len(messages)}")
        for msg in messages[-5:]:
            print(f"     {msg.sender_type.value:7} {msg.message_type.value:5} {msg.content!r}")
    except Exception as exc:
        failed = True
        line("FAIL", "read_visible_messages", str(exc))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
