from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.domain.enums import ConversationType  # noqa: E402
from wx_ai_assistant.domain.models import ConversationIdentity  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else "uia-alt-s-single"
    identity = ConversationIdentity("conv_current", ConversationType.FRIEND, "当前会话")
    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2
    print(f"current={driver.get_current_conversation()}")
    current = driver.get_current_conversation()
    if current is None:
        print("ABORT: 当前会话标题不可读，不执行发送。")
        return 3
    identity.display_name = current.display_name
    identity.remark_name = current.remark_name

    input_box = driver._locate_required("input_box")
    print(f"input_box name={getattr(input_box, 'Name', '')!r} rect={getattr(input_box, 'BoundingRectangle', '')!r}")
    driver._set_focus_no_mouse(input_box)
    driver._clear_input_no_mouse()
    driver._paste_text(text)
    time.sleep(0.2)
    print("sent_keys=Alt+S")
    driver._send_alt_s()
    time.sleep(1.0)
    visible = driver.read_visible_text_messages(identity)
    for msg in visible[-8:]:
        print(f"{msg.sender_type.value}\t{msg.content!r}")
    ok = any(msg.sender_type.value == "self" and msg.content.strip() == text for msg in visible[-10:])
    print(f"verified={ok}")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
