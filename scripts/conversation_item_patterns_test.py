from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


PATTERNS = [
    ("InvokePattern", "InvokePattern"),
    ("SelectionItemPattern", "SelectionItemPattern"),
    ("LegacyIAccessiblePattern", "LegacyIAccessiblePattern"),
    ("ScrollItemPattern", "ScrollItemPattern"),
]


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "文件传输助手"
    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2
    conversation_list = driver._locate_required("conversation_list")
    for item in conversation_list.GetChildren():
        name = str(getattr(item, "Name", "") or "")
        if name != target:
            continue
        print(f"target name={name!r} rect={getattr(item, 'BoundingRectangle', '')!r}")
        for label, attr in PATTERNS:
            pattern_id = getattr(driver._auto.PatternId, attr)
            try:
                pattern = item.GetPattern(pattern_id)
                print(f"{label}: {'yes' if pattern is not None else 'no'}")
                if label == "LegacyIAccessiblePattern" and pattern is not None:
                    print(f"  legacy name={pattern.Name!r} default_action={pattern.DefaultAction!r} role={pattern.Role!r} state={pattern.State!r}")
            except Exception as exc:
                print(f"{label}: error={exc}")
        return 0
    print(f"target {target!r} not found")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
