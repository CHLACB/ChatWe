from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    locator_path = Path("config/wechat_locators.local.json")
    driver = UiaWechatDriver(locator_path)
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    for key in ["search_box", "conversation_list", "chat_title", "message_list", "input_box", "send_button"]:
        try:
            control = driver._locate_required(key)  # Diagnostic script only.
            print(
                f"OK {key}: "
                f"name={getattr(control, 'Name', '')!r} "
                f"type={getattr(control, 'ControlTypeName', '')!r} "
                f"rect={getattr(control, 'BoundingRectangle', '')!r}"
            )
        except Exception as exc:
            print(f"FAIL {key}: {exc}")
            locator = (driver._locators or {}).get(key) or {}
            print(f"Candidates for {key}:")
            for control in driver._iter_controls(driver._window):
                if driver._matches(control, locator):
                    print(
                        "  - "
                        f"name={getattr(control, 'Name', '')!r} "
                        f"type={getattr(control, 'ControlTypeName', '')!r} "
                        f"rect={getattr(control, 'BoundingRectangle', '')!r}"
                    )
            return 3

    print(f"current_conversation={driver.get_current_conversation()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
