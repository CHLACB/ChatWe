from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "文件传输助手"
    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    print("ABORT: search_box 无鼠标聚焦在本机未验证，会把文本落入聊天输入框。该测试已停用。")
    print(f"keyword={keyword!r}")
    return 3

    conversation_list = driver._locate_required("conversation_list")
    items = list(conversation_list.GetChildren())
    print(f"conversation_items={len(items)}")
    for item in items[:20]:
        print(f"item name={getattr(item, 'Name', '')!r} type={getattr(item, 'ControlTypeName', '')!r} rect={getattr(item, 'BoundingRectangle', '')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
