from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict
from typing import Any, Iterable

from wx_ai_assistant.ports.wechat_driver import ControlNode, WindowInfo


WECHAT_39_MAIN_CLASS = "WeChatMainWndForPC"
WECHAT_VERSION = "3.9.12.56"


def require_uiautomation():
    try:
        import uiautomation as auto  # type: ignore
        return auto
    except ImportError as exc:
        raise RuntimeError("缺少 uiautomation。请在 Windows 环境执行: pip install uiautomation") from exc


def enum_top_level_windows() -> list[WindowInfo]:
    """Enumerate top-level windows using Win32.

    Verified stable input:
      - WeChat PC 3.9.x main window class candidate: WeChatMainWndForPC.
    Failure fallback:
      - Return all visible top-level windows so the operator can inspect title/class/pid.
    """

    user32 = ctypes.windll.user32
    windows: list[WindowInfo] = []

    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindow(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        windows.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title_buffer.value,
                class_name=class_buffer.value,
                pid=int(pid.value) if pid.value else None,
                visible=bool(user32.IsWindowVisible(hwnd)),
                minimized=bool(user32.IsIconic(hwnd)),
            )
        )
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return windows


def find_wechat_main_window() -> tuple[WindowInfo | None, list[WindowInfo]]:
    windows = enum_top_level_windows()
    for wnd in windows:
        if wnd.class_name == WECHAT_39_MAIN_CLASS:
            return wnd, windows
    for wnd in windows:
        if "微信" in wnd.title or "WeChat" in wnd.title:
            return wnd, windows
    return None, windows


def ensure_window_foreground(hwnd: int) -> tuple[bool, str]:
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return False, f"窗口不存在: hwnd={hwnd}"
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    else:
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
    user32.SetForegroundWindow(hwnd)
    return True, "window activated"


def control_from_hwnd(auto: Any, hwnd: int) -> Any:
    if hasattr(auto, "ControlFromHandle"):
        try:
            return auto.ControlFromHandle(hwnd)
        except Exception:
            pass
    return auto.WindowControl(searchDepth=1, NativeWindowHandle=hwnd)


def snapshot_control(control: Any, depth: int) -> ControlNode:
    def safe(attr: str) -> str:
        try:
            value = getattr(control, attr)
            if callable(value):
                value = value()
            return str(value or "")
        except Exception:
            return ""

    try:
        rect = control.BoundingRectangle
        bounding = str(rect)
    except Exception:
        bounding = ""

    try:
        children_count = len(control.GetChildren())
    except Exception:
        children_count = 0

    return ControlNode(
        depth=depth,
        name=safe("Name"),
        control_type=safe("ControlTypeName"),
        class_name=safe("ClassName"),
        automation_id=safe("AutomationId"),
        bounding_rectangle=bounding,
        children_count=children_count,
    )


def dump_tree_nodes(control: Any, max_depth: int = 6, depth: int = 0, nodes: list[ControlNode] | None = None) -> list[ControlNode]:
    if nodes is None:
        nodes = []
    nodes.append(snapshot_control(control, depth))
    if depth >= max_depth:
        return nodes
    try:
        children = control.GetChildren()
    except Exception:
        children = []
    for child in children:
        dump_tree_nodes(child, max_depth=max_depth, depth=depth + 1, nodes=nodes)
    return nodes


def dump_tree(control: Any, max_depth: int = 6, depth: int = 0, lines: list[str] | None = None) -> list[str]:
    if lines is None:
        lines = []
    snap = snapshot_control(control, depth)
    indent = "  " * depth
    lines.append(
        f"{indent}- depth={snap.depth} name={snap.name!r} type={snap.control_type!r} "
        f"class={snap.class_name!r} automation_id={snap.automation_id!r} "
        f"rect={snap.bounding_rectangle!r} children={snap.children_count}"
    )
    if depth >= max_depth:
        return lines
    try:
        children = control.GetChildren()
    except Exception:
        children = []
    for child in children:
        dump_tree(child, max_depth=max_depth, depth=depth + 1, lines=lines)
    return lines


def nodes_to_dicts(nodes: Iterable[ControlNode]) -> list[dict]:
    return [asdict(node) for node in nodes]
