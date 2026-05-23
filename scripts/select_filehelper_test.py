from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.domain.enums import ConversationType  # noqa: E402
from wx_ai_assistant.domain.models import ConversationIdentity  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def print_current(driver: UiaWechatDriver, label: str) -> object:
    current = driver.get_current_conversation()
    print(f"{label}={current}")
    if current is not None:
        return current

    print(f"{label}_chat_title_diagnostic:")
    locator = (driver._locators or {}).get("chat_title") or {}
    candidates = [c for c in driver._iter_controls(driver._window) if driver._matches(c, locator)]
    for candidate in candidates[:12]:
        print(
            "  candidate "
            f"name={getattr(candidate, 'Name', '')!r} "
            f"type={getattr(candidate, 'ControlTypeName', '')!r} "
            f"rect={getattr(candidate, 'BoundingRectangle', '')!r}"
        )
    if len(candidates) > 12:
        print(f"  ... {len(candidates) - 12} more")
    return None


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "文件传输助手"
    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2
    print_current(driver, "before")
    identity = ConversationIdentity("conv_select", ConversationType.FRIEND, target, remark_name=target)
    conversation_list = driver._locate_required("conversation_list")
    for item in conversation_list.GetChildren():
        if str(getattr(item, "Name", "") or "") == target:
            print(f"activating name={target!r} rect={getattr(item, 'BoundingRectangle', '')!r}")
            focused_ok = driver._focus_control_for_keyboard(item)
            focused = driver._focused_control()
            print(
                "focused_after_setfocus="
                f"ok={focused_ok} "
                f"name={getattr(focused, 'Name', '')!r} "
                f"type={getattr(focused, 'ControlTypeName', '')!r} "
                f"rect={getattr(focused, 'BoundingRectangle', '')!r}"
            )
            if not focused_ok:
                print("ABORT: target list item did not receive keyboard focus; no Enter was sent.")
                return 5
            driver._send_enter()
            time.sleep(1.0)
            after = print_current(driver, "after")
            return 0 if after and after.display_name == target else 3
    print(f"target {target!r} not found")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
