from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump visible WeChat conversation-list items without switching chats.")
    parser.add_argument("--locator-path", default="config/wechat_locators.local.json", help="本机 locator 配置路径")
    parser.add_argument("--out", default="", help="输出 JSON 文件路径；为空则输出到终端")
    args = parser.parse_args()

    driver = UiaWechatDriver(Path(args.locator_path))
    status = driver.status()
    if not status.ok:
        print(status)
        return 2
    try:
        items = driver.dump_conversation_list_items()
    except Exception as exc:
        print(f"dump failed: {exc}")
        return 3

    text = json.dumps(items, ensure_ascii=False, indent=2)
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
