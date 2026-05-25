from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.domain.enums import ConversationType  # noqa: E402
from wx_ai_assistant.domain.models import ConversationIdentity  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose no-mouse switch_conversation for one friend target.")
    parser.add_argument("target", help="好友私聊显示名，例如 A2")
    parser.add_argument("--locator-path", default="config/wechat_locators.local.json")
    args = parser.parse_args()

    driver = UiaWechatDriver(Path(args.locator_path))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    before = driver.get_current_conversation()
    print(f"before={before}")

    identity = ConversationIdentity(
        conversation_id=f"diagnose_{args.target}",
        conversation_type=ConversationType.FRIEND,
        display_name=args.target,
        remark_name=args.target,
        local_id=args.target,
    )
    switch_status = driver.switch_conversation(identity)
    print(f"switch_status={switch_status}")

    after = driver.get_current_conversation()
    print(f"after={after}")

    if not switch_status.ok:
        print("diagnosis:")
        print("  - search_box ok if initialize succeeded but switch failed after Ctrl+F/search.")
        print("  - if error mentions chat_title, WeChat did not expose a verifiable chat title after switching.")
        print("  - dump current window after failure:")
        print("    .\\.conda\\python.exe scripts\\dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 14 --out docs\\wechat_switch_failure_dump.md")
        return 1

    messages = driver.read_visible_text_messages(identity)
    print(f"visible_messages={len(messages)}")
    for msg in messages[-10:]:
        print(f"{msg.sender_type.value:7} {msg.content!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
