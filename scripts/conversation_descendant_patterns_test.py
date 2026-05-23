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
    target_item = None
    for item in conversation_list.GetChildren():
        if str(getattr(item, "Name", "") or "") == target:
            target_item = item
            break
    if target_item is None:
        print(f"target {target!r} not found")
        return 3

    print(f"target item name={getattr(target_item, 'Name', '')!r} rect={getattr(target_item, 'BoundingRectangle', '')!r}")
    for control in driver._iter_controls(target_item, max_depth=6):
        name = str(getattr(control, "Name", "") or "")
        ctype = str(getattr(control, "ControlTypeName", "") or "")
        rect = getattr(control, "BoundingRectangle", "")
        if not name and ctype != "ButtonControl":
            continue
        print(f"control name={name!r} type={ctype!r} rect={rect!r}")
        for label, attr in PATTERNS:
            pattern_id = getattr(driver._auto.PatternId, attr)
            try:
                pattern = control.GetPattern(pattern_id)
                available = pattern is not None
                print(f"  {label}: {'yes' if available else 'no'}")
                if label == "LegacyIAccessiblePattern" and available:
                    print(f"    legacy name={pattern.Name!r} default_action={pattern.DefaultAction!r} role={pattern.Role!r} state={pattern.State!r}")
            except Exception as exc:
                print(f"  {label}: error={exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
