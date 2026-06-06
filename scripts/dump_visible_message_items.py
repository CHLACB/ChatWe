from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def dump_visible_message_items(driver: UiaWechatDriver, capture_media: bool = False) -> list[dict]:
    current = driver.get_current_conversation()
    message_list = driver._locate_required("message_list")
    rows = []
    for index, item in enumerate(driver._message_items(message_list), 1):
        content = driver._visible_message_content(item)
        message_type = driver._visible_message_type(content) if content else None
        sender = driver._classify_sender(item, current)
        fingerprint = ""
        media_path = None
        if current is not None and content and message_type is not None:
            capture_control = driver._media_capture_control(item, sender, message_type)
            fingerprint = driver._visible_message_fingerprint(
                current,
                capture_control or item,
                sender,
                content,
                index,
                message_type=message_type,
            )
            if capture_media:
                media_path = driver._capture_visible_media_item(current, item, sender, message_type, fingerprint)
        rows.append(
            {
                "index": index,
                "name": str(getattr(item, "Name", "") or ""),
                "detected_content": content,
                "detected_message_type": message_type.value if message_type is not None else "",
                "detected_sender": sender.value,
                "fingerprint": fingerprint,
                "media_path": media_path,
                "control_type": str(getattr(item, "ControlTypeName", "") or ""),
                "class_name": str(getattr(item, "ClassName", "") or ""),
                "automation_id": str(getattr(item, "AutomationId", "") or ""),
                "bounding_rectangle": str(getattr(item, "BoundingRectangle", "") or ""),
                "children_count": driver._children_count(item),
                "children": [
                    {
                        "name": str(getattr(child, "Name", "") or ""),
                        "control_type": str(getattr(child, "ControlTypeName", "") or ""),
                        "class_name": str(getattr(child, "ClassName", "") or ""),
                        "automation_id": str(getattr(child, "AutomationId", "") or ""),
                        "bounding_rectangle": str(getattr(child, "BoundingRectangle", "") or ""),
                    }
                    for child in driver._iter_controls(item, max_depth=3)
                    if child is not item
                ],
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump current chat visible message items for media locator verification.")
    parser.add_argument("--locator-path", default="config/wechat_locators.local.json", help="本机 locator 配置路径")
    parser.add_argument("--out", default="", help="输出 JSON 文件路径；为空则输出到终端")
    parser.add_argument("--capture-media", action="store_true", help="同时尝试截取图片/表情包消息 item 到 data/media/uia_visible")
    args = parser.parse_args()

    driver = UiaWechatDriver(Path(args.locator_path))
    status = driver.status()
    if not status.ok:
        print(status)
        return 2
    try:
        rows = dump_visible_message_items(driver, capture_media=args.capture_media)
    except Exception as exc:
        print(f"dump failed: {exc}")
        return 3

    text = json.dumps(rows, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"written: {out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
