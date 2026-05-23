from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    search_box = driver._locate_required("search_box")
    print(
        "search_box "
        f"name={getattr(search_box, 'Name', '')!r} "
        f"type={getattr(search_box, 'ControlTypeName', '')!r} "
        f"rect={getattr(search_box, 'BoundingRectangle', '')!r}"
    )

    focused = driver._focus_search_box_with_hotkey(search_box)
    in_search = focused is not None
    print(
        "focused_after_ctrl_f="
        f"ok={in_search} "
        f"name={getattr(focused, 'Name', '')!r} "
        f"type={getattr(focused, 'ControlTypeName', '')!r} "
        f"rect={getattr(focused, 'BoundingRectangle', '')!r}"
    )
    if not in_search:
        print("ABORT: Ctrl+F did not focus the left search box. No text was typed.")
        return 3
    print("OK: Ctrl+F focused the verified search box. No text was typed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
