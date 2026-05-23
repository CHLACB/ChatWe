from __future__ import annotations

from pathlib import Path
import sys

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
    identity = ConversationIdentity(
        conversation_id="conv_filehelper_switch_test",
        conversation_type=ConversationType.FRIEND,
        display_name="文件传输助手",
        remark_name="文件传输助手",
        local_id="filehelper",
    )
    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2
    print_current(driver, "before")
    switch_status = driver.switch_conversation(identity)
    print(f"switch_status={switch_status}")
    after = print_current(driver, "after")
    return 0 if switch_status.ok and after and after.display_name == "文件传输助手" else 3


if __name__ == "__main__":
    raise SystemExit(main())
