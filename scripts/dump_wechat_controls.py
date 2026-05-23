from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

# Allow running from project root without installation.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.infrastructure.wechat.uia_finder import (  # noqa: E402
    WECHAT_39_MAIN_CLASS,
    control_from_hwnd,
    dump_tree,
    enum_top_level_windows,
    find_wechat_main_window,
    require_uiautomation,
)


def list_windows() -> str:
    lines = ["# Top-level windows", ""]
    for i, wnd in enumerate(enum_top_level_windows()):
        lines.append(
            f"{i}. hwnd={wnd.hwnd} title={wnd.title!r} class_name={wnd.class_name!r} "
            f"pid={wnd.pid} visible={wnd.visible} minimized={wnd.minimized}"
        )
    return "\n".join(lines)


def find_window(auto, title_contains: str | None, class_name: str | None, hwnd: int | None):
    if hwnd:
        return control_from_hwnd(auto, hwnd)
    if not title_contains and not class_name:
        info, _ = find_wechat_main_window()
        if info:
            return control_from_hwnd(auto, info.hwnd)
        return None
    for wnd in enum_top_level_windows():
        if title_contains and title_contains not in wnd.title:
            continue
        if class_name and class_name != wnd.class_name:
            continue
        return control_from_hwnd(auto, wnd.hwnd)
    return None


def matches(control: Any, locator: dict) -> bool:
    def value(attr: str) -> str:
        try:
            return str(getattr(control, attr) or "")
        except Exception:
            return ""

    if locator.get("automation_id") and value("AutomationId") != locator["automation_id"]:
        return False
    if locator.get("class_name") and value("ClassName") != locator["class_name"]:
        return False
    if locator.get("control_type") and value("ControlTypeName") != locator["control_type"]:
        return False
    if locator.get("name_contains") and locator["name_contains"] not in value("Name"):
        return False
    return any(locator.get(k) for k in ("automation_id", "class_name", "control_type", "name_contains"))


def iter_controls(root: Any, depth: int = 0, max_depth: int = 12):
    if depth > max_depth:
        return
    yield root
    try:
        children = root.GetChildren()
    except Exception:
        children = []
    for child in children:
        yield from iter_controls(child, depth + 1, max_depth)


def locate_from_config(root: Any, locators_path: Path, key: str):
    if not locators_path.exists():
        raise RuntimeError(f"locator 文件不存在，无法 dump {key} 附近控件: {locators_path}")
    locators = json.loads(locators_path.read_text(encoding="utf-8"))
    locator = locators.get(key) or {}
    if not locator:
        raise RuntimeError(f"locator 中缺少 {key}。请先 dump 全窗口，再补充 {key} 的稳定字段。")
    candidates = [control for control in iter_controls(root) if matches(control, locator)]
    if not candidates:
        raise RuntimeError(f"按当前 locator 未找到 {key}。请重新 dump 全窗口并检查字段。")
    index = locator.get("index")
    if index is not None:
        return candidates[int(index)]
    if len(candidates) != 1:
        raise RuntimeError(f"{key} 匹配到 {len(candidates)} 个候选。请补充字段或已验证 index。")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump Windows UI Automation control tree for local WeChat inspection.")
    parser.add_argument("--list-windows", action="store_true", help="List top-level windows only.")
    parser.add_argument("--hwnd", type=int, help="Dump a top-level window by hwnd.")
    parser.add_argument("--title-contains", help="Find a top-level window whose title contains this text.")
    parser.add_argument("--class-name", default=WECHAT_39_MAIN_CLASS, help="Find a top-level window whose ClassName equals this value.")
    parser.add_argument("--depth", type=int, default=6, help="Max tree depth to dump.")
    parser.add_argument("--near", choices=["chat_title", "search_box", "message_list", "input_box"], help="Dump subtree near a configured locator.")
    parser.add_argument("--locators", default="config/wechat_locators.local.json", help="Locator json used with --near.")
    parser.add_argument("--out", help="Output markdown file path. Defaults to stdout.")
    args = parser.parse_args()

    if args.list_windows:
        text = list_windows()
    else:
        auto = require_uiautomation()
        wnd = find_window(auto, args.title_contains, args.class_name, args.hwnd)
        if wnd is None:
            print("未找到匹配窗口。请先运行 --list-windows 查看 hwnd/title/class_name/pid。", file=sys.stderr)
            return 2
        root = wnd
        title = "# UIA control tree"
        if args.near:
            try:
                root = locate_from_config(wnd, Path(args.locators), args.near)
                title = f"# UIA nearby dump: {args.near}"
            except Exception as exc:
                print(str(exc), file=sys.stderr)
                return 3
        lines = [title, "", "```text"]
        lines.extend(dump_tree(root, max_depth=args.depth))
        lines.append("```")
        text = "\n".join(lines)

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
