from __future__ import annotations

import json
import re
import time
from pathlib import Path
from threading import RLock
from typing import Any

from wx_ai_assistant.core.exceptions import DriverNotConfiguredError
from wx_ai_assistant.domain.enums import ConversationType, MessageType, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.infrastructure.wechat.uia_finder import (
    WECHAT_39_MAIN_CLASS,
    WECHAT_VERSION,
    control_from_hwnd,
    dump_tree_nodes,
    ensure_window_foreground,
    find_wechat_main_window,
    nodes_to_dicts,
    require_uiautomation,
)
from wx_ai_assistant.ports.wechat_driver import DriverStatus, SendResult, WechatDriver, WindowInfo


class UiaWechatDriver(WechatDriver):
    """Real UIA driver for locally verified WeChat controls.

    Verified built-in rule:
      - WeChat PC 3.9.12.56 main window class candidate: WeChatMainWndForPC.
    Verification source:
      - User-provided project requirement plus local Win32 top-level window enumeration.
    Fallback:
      - Enumerate all top-level windows and return hwnd/title/class_name/pid details.
    Unknown controls:
      - Search box, input box and message area must come from local dump/Inspect data.
    """

    def __init__(self, locator_path: Path):
        self.locator_path = Path(locator_path)
        self._lock = RLock()
        self._auto = None
        self._locators: dict[str, Any] | None = None
        self._window = None
        self._window_info: WindowInfo | None = None
        self._current_identity: ConversationIdentity | None = None
        self.last_send_method: str | None = None

    def initialize(self) -> DriverStatus:
        with self._lock:
            try:
                self._auto = require_uiautomation()
                self._locators = self._load_locators()
                self._window = self._find_window()
                self.restore_and_activate()
                return DriverStatus(ok=True, mode="uia", message="UIA driver initialized", details=self._window_details())
            except Exception as exc:
                return DriverStatus(ok=False, mode="uia", message=str(exc), details=self._window_details())

    def status(self) -> DriverStatus:
        try:
            self._ensure_auto()
            if self._locators is None:
                self._locators = self._load_locators()
            if self._window is None:
                self._window = self._find_window()
            return DriverStatus(ok=True, mode="uia", message="WeChat window found", details=self._window_details())
        except Exception as exc:
            return DriverStatus(ok=False, mode="uia", message=str(exc), details=self._window_details())

    def switch_conversation(self, identity: ConversationIdentity) -> DriverStatus:
        with self._lock:
            try:
                self._ensure_ready()
                self.restore_and_activate()
                current = self.get_current_conversation()
                if self._identity_title_matches(identity, current):
                    self._current_identity = identity
                    return DriverStatus(ok=True, mode="uia", message=f"already on {identity.display_name}", details=self._window_details())

                strategy = (self._locators or {}).get("switch_conversation") or {}
                if not strategy.get("verified"):
                    raise DriverNotConfiguredError(self._missing_control_message("switch_conversation", "搜索框、搜索结果、聊天标题"))

                self._activate_conversation_without_mouse(identity)
                current = self.get_current_conversation()
                if current is None:
                    raise DriverNotConfiguredError("切换会话后无法读取当前聊天标题，请先运行 switch_filehelper_test.py 查看 before/after 和候选。")
                if not self._identity_title_matches(identity, current):
                    raise DriverNotConfiguredError(
                        "切换会话后标题未验证为目标会话。请采集搜索结果和聊天标题控件，避免选中同名会话。"
                    )
                self._current_identity = identity
                return DriverStatus(ok=True, mode="uia", message=f"switched to {identity.display_name}", details=self._window_details())
            except Exception as exc:
                return DriverStatus(ok=False, mode="uia", message=str(exc), details=self._error_details("switch_conversation"))

    def get_current_conversation(self) -> ConversationIdentity | None:
        with self._lock:
            deadline = time.time() + 1.0
            while time.time() < deadline:
                try:
                    self._ensure_ready()
                    title_control = self._locate_required("chat_title")
                    title = str(getattr(title_control, "Name", "") or "").strip()
                    if title:
                        if self._current_identity and title in {self._current_identity.display_name, self._current_identity.remark_name}:
                            return self._current_identity
                        return ConversationIdentity(
                            conversation_id="current_unknown",
                            conversation_type=self._current_identity.conversation_type if self._current_identity else ConversationType.FRIEND,
                            display_name=title,
                        )
                except Exception:
                    pass
                time.sleep(0.1)
            return None

    def read_visible_text_messages(self, identity: ConversationIdentity) -> list[Message]:
        with self._lock:
            self._ensure_ready()
            message_list = self._locate_required("message_list")
            messages: list[Message] = []
            for item in self._message_items(message_list):
                content = str(getattr(item, "Name", "") or "").strip()
                if not content:
                    continue
                messages.append(
                    Message(
                        conversation_id=identity.conversation_id,
                        sender_type=self._classify_sender(item),
                        sender_name="需要补充控件信息" if self._classify_sender(item) == SenderType.UNKNOWN else None,
                        message_type=MessageType.TEXT,
                        content=content,
                    )
                )
            return messages

    def send_text(self, identity: ConversationIdentity, content: str) -> SendResult:
        with self._lock:
            try:
                self._ensure_ready()
                self.restore_and_activate()
                input_box = self._locate_required("input_box")
                send_button = self._locate_optional("send_button")
                method = self._send_configured_method(identity, input_box, send_button, content)
                self.last_send_method = method
                return SendResult(ok=True, message=f"sent via {method}", details={**self._window_details(), "send_method": method})
            except Exception as exc:
                return SendResult(ok=False, message=str(exc), details=self._error_details("input_box"))

    def list_windows(self) -> list[dict]:
        _, windows = find_wechat_main_window()
        return [w.__dict__ for w in windows]

    def restore_and_activate(self) -> DriverStatus:
        if self._window_info is None:
            self._find_window()
        assert self._window_info is not None
        ok, message = ensure_window_foreground(self._window_info.hwnd)
        refreshed, _ = find_wechat_main_window()
        if refreshed is not None:
            self._window_info = refreshed
        return DriverStatus(ok=ok, mode="uia", message=message, details=self._window_details())

    def window_exists(self) -> DriverStatus:
        try:
            self._ensure_ready()
            return DriverStatus(ok=True, mode="uia", message="window exists", details=self._window_details())
        except Exception as exc:
            return DriverStatus(ok=False, mode="uia", message=str(exc), details=self._window_details())

    def dump_current_window_controls(self, depth: int = 6) -> list[dict]:
        self._ensure_ready()
        return nodes_to_dicts(dump_tree_nodes(self._window, max_depth=depth))

    def _load_locators(self) -> dict[str, Any]:
        if not self.locator_path.exists():
            return {}
        return json.loads(self.locator_path.read_text(encoding="utf-8"))

    def _find_window(self):
        self._ensure_auto()
        assert self._auto is not None
        info, windows = find_wechat_main_window()
        if info is None:
            raise DriverNotConfiguredError(
                "未找到微信主窗口。已枚举顶层窗口，请确认微信已登录，或反馈 hwnd/title/class_name/pid。"
            )
        self._window_info = info
        try:
            self._window = control_from_hwnd(self._auto, info.hwnd)
        except Exception as exc:
            raise DriverNotConfiguredError(f"hwnd 转 UIA WindowControl 失败: hwnd={info.hwnd}, error={exc}") from exc
        return self._window

    def _ensure_auto(self) -> None:
        if self._auto is None:
            self._auto = require_uiautomation()

    def _ensure_ready(self) -> None:
        self._ensure_auto()
        if self._locators is None:
            self._locators = self._load_locators()
        if self._window is None:
            self._window = self._find_window()

    def _window_details(self) -> dict:
        details = {
            "wechat_version": WECHAT_VERSION,
            "verified_main_class": WECHAT_39_MAIN_CLASS,
            "locator_path": str(self.locator_path),
        }
        if self._window_info:
            details["window"] = self._window_info.__dict__
        else:
            _, windows = find_wechat_main_window()
            details["top_level_windows"] = [w.__dict__ for w in windows[:50]]
        return details

    def _error_details(self, missing: str) -> dict:
        details = self._window_details()
        details["missing_control"] = missing
        details["dump_commands"] = [
            "python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --depth 8 --out docs/wechat_main_dump.md",
            f"python scripts/dump_wechat_controls.py --class-name WeChatMainWndForPC --near {missing} --depth 5 --out docs/wechat_{missing}_nearby.md",
        ]
        details["required_fields"] = ["name", "class_name", "control_type", "automation_id", "bounding_rectangle", "depth", "children_count"]
        return details

    def _missing_control_message(self, key: str, human_name: str) -> str:
        return (
            f"缺少已验证的 {human_name} 控件信息，不能凭猜测定位 {key}。"
            "请使用 scripts/dump_wechat_controls.py 或 Inspect.exe 采集 name/class_name/control_type/"
            "automation_id/bounding_rectangle/depth/children_count 后写入 config/wechat_locators.local.json。"
        )

    def _locate_required(self, key: str):
        locator = (self._locators or {}).get(key) or {}
        if not locator:
            raise DriverNotConfiguredError(self._missing_control_message(key, key))

        stable_fields = ["automation_id", "class_name", "control_type", "name_contains"]
        if locator.get("index") is not None and not any(locator.get(field) for field in stable_fields):
            raise DriverNotConfiguredError(f"{key} 不能只配置 index。请先采集稳定字段，再把 index 作为辅助条件。")

        candidates = [c for c in self._iter_controls(self._window) if self._matches(c, locator)]
        index = locator.get("index")
        if index is not None:
            try:
                return candidates[int(index)]
            except (IndexError, ValueError):
                raise DriverNotConfiguredError(f"{key} 按已验证 selector 找到 {len(candidates)} 个候选，但 index={index} 不存在。")
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise DriverNotConfiguredError(f"未找到 {key} 控件。请 dump {key} 附近控件并更新 locator。")
        raise DriverNotConfiguredError(f"{key} 匹配到 {len(candidates)} 个候选。请补充 automation_id/class_name/name_contains 或已验证 index。")

    def _locate_optional(self, key: str):
        try:
            return self._locate_required(key)
        except Exception:
            return None

    def _iter_controls(self, root: Any, depth: int = 0, max_depth: int = 20):
        if depth > max_depth:
            return
        yield root
        try:
            children = root.GetChildren()
        except Exception:
            children = []
        for child in children:
            yield from self._iter_controls(child, depth + 1, max_depth)

    def _matches(self, control: Any, locator: dict[str, Any]) -> bool:
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
        if locator.get("name_not_matches") and re.search(str(locator["name_not_matches"]), value("Name")):
            return False
        if locator.get("name_not_empty") and not value("Name").strip():
            return False
        if locator.get("region") and not self._in_region(control, locator["region"]):
            return False
        if locator.get("max_width_ratio") is not None:
            root_rect = self._rect_tuple(self._window)
            rect = self._rect_tuple(control)
            if root_rect is None or rect is None:
                return False
            root_width = max(root_rect[2] - root_rect[0], 1)
            control_width = max(rect[2] - rect[0], 0)
            if control_width / root_width > float(locator["max_width_ratio"]):
                return False
        return any(locator.get(k) for k in ("automation_id", "class_name", "control_type", "name_contains", "name_not_empty"))

    def _in_region(self, control: Any, region: str) -> bool:
        root_rect = self._rect_tuple(self._window)
        rect = self._rect_tuple(control)
        if root_rect is None or rect is None:
            return False

        left, top, right, bottom = rect
        root_left, root_top, root_right, root_bottom = root_rect
        width = max(root_right - root_left, 1)
        height = max(root_bottom - root_top, 1)
        center_x = ((left + right) / 2 - root_left) / width
        center_y = ((top + bottom) / 2 - root_top) / height

        if region == "conversation_panel":
            return 0.05 <= center_x <= 0.36
        if region == "conversation_panel_header":
            return 0.05 <= center_x <= 0.36 and center_y <= 0.16
        if region == "chat_panel":
            return center_x >= 0.33
        if region == "chat_header":
            return 0.33 <= center_x <= 0.75 and 0.0 <= center_y <= 0.075
        if region == "message_area":
            return center_x >= 0.33 and 0.08 <= center_y <= 0.82
        if region == "input_area":
            return center_x >= 0.33 and center_y >= 0.78
        return True

    def _rect_tuple(self, control: Any) -> tuple[int, int, int, int] | None:
        try:
            text = str(control.BoundingRectangle)
        except Exception:
            return None
        match = re.search(r"\((-?\d+),(-?\d+),(-?\d+),(-?\d+)\)", text)
        if not match:
            return None
        return tuple(int(part) for part in match.groups())  # type: ignore[return-value]

    def _message_items(self, message_list: Any) -> list[Any]:
        try:
            return list(message_list.GetChildren())
        except Exception:
            return []

    def _identity_title_matches(self, expected: ConversationIdentity, actual: ConversationIdentity | None) -> bool:
        if actual is None:
            return False
        expected_names = {expected.display_name, expected.remark_name} - {None, ""}
        actual_names = {actual.display_name, actual.remark_name} - {None, ""}
        return bool(expected_names & actual_names)

    def _activate_conversation_without_mouse(self, identity: ConversationIdentity) -> None:
        try:
            self._activate_conversation_by_search_hotkey(identity)
            return
        except DriverNotConfiguredError:
            raise
        except Exception as exc:
            raise DriverNotConfiguredError(f"搜索热键切换会话失败: {exc}") from exc

    def _activate_conversation_by_search_hotkey(self, identity: ConversationIdentity) -> None:
        assert self._auto is not None
        names = [name for name in [identity.display_name, identity.remark_name] if name]
        if not names:
            raise DriverNotConfiguredError("目标会话缺少 display_name/remark_name，无法搜索切换。")
        search_text = names[0]

        search_box = self._locate_required("search_box")
        self._auto.SendKeys("{Ctrl}f")
        time.sleep(0.2)

        focused = self._focused_control()
        if focused is None or not self._same_or_child_rect(search_box, focused):
            raise DriverNotConfiguredError(
                "Ctrl+F 后焦点未落到左侧搜索框，已停止输入，避免误写入聊天输入框。"
                f" focused_name={getattr(focused, 'Name', '')!r}, "
                f"focused_type={getattr(focused, 'ControlTypeName', '')!r}, "
                f"focused_rect={getattr(focused, 'BoundingRectangle', '')!r}"
            )

        self._clear_input_no_mouse()
        self._paste_text(search_text)
        time.sleep(0.25)
        self._send_enter()
        time.sleep(0.35)

    def _activate_conversation_from_list(self, identity: ConversationIdentity) -> None:
        names = {identity.display_name, identity.remark_name} - {None, ""}
        conversation_list = self._locate_required("conversation_list")
        last_candidates: list[str] = []
        try:
            items = list(conversation_list.GetChildren())
        except Exception:
            items = []
        for item in items:
            item_name = str(getattr(item, "Name", "") or "").strip()
            if item_name:
                last_candidates.append(item_name)
            if item_name in names:
                self._activate_list_item_no_mouse(item)
                time.sleep(0.8)
                return
        raise DriverNotConfiguredError(f"当前可见会话列表中未找到目标会话 {names}，候选={last_candidates[-10:]}。搜索框无鼠标聚焦未验证，已禁用。")

    def _activate_list_item_no_mouse(self, item: Any) -> None:
        assert self._auto is not None
        if self._focus_control_for_keyboard(item):
            self._send_enter()
            return
        raise DriverNotConfiguredError("目标会话项无法获得键盘焦点，不能无鼠标激活。请继续采集会话列表焦点/键盘导航信息。")

    def _focus_control_for_keyboard(self, control: Any) -> bool:
        if not hasattr(control, "SetFocus"):
            return False
        try:
            control.SetFocus()
            time.sleep(0.2)
        except Exception:
            return False
        focused = self._focused_control()
        if focused is None:
            return False
        return self._same_or_child_rect(control, focused)

    def _focused_control(self) -> Any | None:
        assert self._auto is not None
        try:
            return self._auto.GetFocusedControl()
        except Exception:
            return None

    def _same_or_child_rect(self, parent: Any, child: Any) -> bool:
        parent_rect = self._rect_tuple(parent)
        child_rect = self._rect_tuple(child)
        if parent_rect is None or child_rect is None:
            return False
        parent_left, parent_top, parent_right, parent_bottom = parent_rect
        child_left, child_top, child_right, child_bottom = child_rect
        return (
            parent_left <= child_left <= child_right <= parent_right
            and parent_top <= child_top <= child_bottom <= parent_bottom
        )

    def _classify_sender(self, item: Any) -> SenderType:
        locator = (self._locators or {}).get("message_item") or {}
        name = str(getattr(item, "Name", "") or "")
        class_name = str(getattr(item, "ClassName", "") or "")
        if locator.get("self_avatar_name") and self._has_avatar(item, locator["self_avatar_name"], locator.get("self_avatar_region")):
            return SenderType.SELF
        if locator.get("self_name_contains") and locator["self_name_contains"] in name:
            return SenderType.SELF
        if locator.get("other_name_contains") and locator["other_name_contains"] in name:
            return SenderType.OTHER
        if locator.get("system_class_name") and locator["system_class_name"] == class_name:
            return SenderType.SYSTEM
        if self._looks_like_time_marker(name):
            return SenderType.SYSTEM
        return SenderType.UNKNOWN

    def _has_avatar(self, item: Any, avatar_name: str, region: str | None) -> bool:
        item_rect = self._rect_tuple(item)
        if item_rect is None:
            return False
        item_left, _, item_right, _ = item_rect
        item_width = max(item_right - item_left, 1)
        for child in self._iter_controls(item, max_depth=4):
            try:
                if str(getattr(child, "Name", "") or "") != avatar_name:
                    continue
                if str(getattr(child, "ControlTypeName", "") or "") != "ButtonControl":
                    continue
            except Exception:
                continue
            if region == "right":
                child_rect = self._rect_tuple(child)
                if child_rect is None:
                    continue
                child_left, _, child_right, _ = child_rect
                child_center_x = ((child_left + child_right) / 2 - item_left) / item_width
                if child_center_x < 0.75:
                    continue
            return True
        return False

    def _looks_like_time_marker(self, value: str) -> bool:
        return bool(re.search(r"(\d{4}年\d{1,2}月\d{1,2}日|星期.|AM|PM)", value))

    def _focus(self, control: Any) -> None:
        self._click(control)
        if hasattr(control, "SetFocus"):
            try:
                control.SetFocus()
            except Exception:
                pass

    def _click(self, control: Any) -> None:
        if hasattr(control, "Click"):
            control.Click()
            return
        rect = self._rect_tuple(control)
        if rect and self._auto is not None:
            left, top, right, bottom = rect
            self._auto.Click((left + right) // 2, (top + bottom) // 2)

    def _set_focus_no_mouse(self, control: Any) -> None:
        if hasattr(control, "SetFocus"):
            control.SetFocus()

    def _send_configured_method(self, identity: ConversationIdentity, input_box: Any, send_button: Any | None, content: str) -> str:
        method = ((self._locators or {}).get("send_behavior") or {}).get("method", "clipboard_alt_s")
        self._set_focus_no_mouse(input_box)
        self._clear_input_no_mouse()

        if method == "clipboard_alt_s":
            self._paste_text(content)
            time.sleep(0.2)
            self._send_alt_s()
        elif method == "clipboard_ctrl_enter":
            self._paste_text(content)
            time.sleep(0.2)
            self._send_ctrl_enter()
        elif method == "clipboard_enter":
            self._paste_text(content)
            time.sleep(0.2)
            self._send_enter()
        elif method == "value_pattern_invoke":
            if send_button is None:
                raise DriverNotConfiguredError("send_button 未定位，不能执行 value_pattern_invoke")
            self._set_value_pattern(input_box, content)
            time.sleep(0.2)
            self._invoke_pattern(send_button)
        else:
            raise DriverNotConfiguredError(f"未知 send_behavior.method: {method}")

        if self._sent_message_visible(identity, content):
            return method
        raise DriverNotConfiguredError(f"{method} 执行后未在最近可见消息中确认到自己刚发送的内容")

    def _sent_message_visible(self, identity: ConversationIdentity, content: str) -> bool:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                messages = self.read_visible_text_messages(identity)
            except Exception:
                messages = []
            for msg in reversed(messages[-10:]):
                if msg.content.strip() == content.strip() and msg.sender_type == SenderType.SELF:
                    return True
            time.sleep(0.2)
        return False

    def _set_value_pattern(self, control: Any, content: str) -> None:
        assert self._auto is not None
        pattern = control.GetPattern(self._auto.PatternId.ValuePattern)
        if pattern is None:
            raise DriverNotConfiguredError("input_box 不支持 ValuePattern")
        if getattr(pattern, "IsReadOnly", False):
            raise DriverNotConfiguredError("input_box ValuePattern 为只读")
        pattern.SetValue(content)

    def _invoke_pattern(self, control: Any) -> None:
        assert self._auto is not None
        pattern = control.GetPattern(self._auto.PatternId.InvokePattern)
        if pattern is None:
            raise DriverNotConfiguredError("send_button 不支持 InvokePattern")
        pattern.Invoke()

    def _legacy_default_action(self, control: Any) -> None:
        assert self._auto is not None
        pattern = control.GetPattern(self._auto.PatternId.LegacyIAccessiblePattern)
        if pattern is None:
            raise DriverNotConfiguredError("send_button 不支持 LegacyIAccessiblePattern")
        pattern.DoDefaultAction()

    def _paste_text(self, text: str) -> None:
        assert self._auto is not None
        if hasattr(self._auto, "SetClipboardText"):
            self._auto.SetClipboardText(text)
        else:
            raise DriverNotConfiguredError("uiautomation 不支持 SetClipboardText。请安装可用版本或补充剪贴板实现。")
        self._auto.SendKeys("{Ctrl}v")

    def _clear_input_no_mouse(self) -> None:
        assert self._auto is not None
        self._auto.SendKeys("{Ctrl}a")
        time.sleep(0.05)
        self._auto.SendKeys("{Back}")
        time.sleep(0.05)

    def _send_enter(self) -> None:
        assert self._auto is not None
        self._auto.SendKeys("{Enter}")

    def _send_ctrl_enter(self) -> None:
        assert self._auto is not None
        self._auto.SendKeys("{Ctrl}{Enter}")

    def _send_alt_s(self) -> None:
        assert self._auto is not None
        self._auto.SendKeys("{Alt}s")
