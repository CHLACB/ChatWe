from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.domain.enums import ConversationType  # noqa: E402
from wx_ai_assistant.domain.models import ConversationIdentity  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    identity = ConversationIdentity(
        conversation_id="conv_filehelper_uia_test",
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

    current = driver.get_current_conversation()
    print(f"current={current}")
    messages = driver.read_visible_text_messages(identity)
    print(f"visible_count={len(messages)}")
    for msg in messages[-20:]:
        print(f"{msg.sender_type.value}\t{msg.message_type.value}\t{msg.content}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
