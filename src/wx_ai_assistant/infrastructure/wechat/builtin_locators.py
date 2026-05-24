from __future__ import annotations

from copy import deepcopy
from typing import Any


WECHAT_391256_BUILTIN_LOCATORS: dict[str, Any] = {
    "description": "内置微信 3.9.12.56 UIA 策略。仅使用已在本机验证的语义字段和相对区域，不包含账号私有坐标。",
    "wechat_version": "3.9.12.56",
    "verification_source": [
        "scripts/search_hotkey_focus_test.py 验证 Ctrl+F 可聚焦左侧搜索框",
        "scripts/switch_filehelper_test.py 验证 Ctrl+F 搜索 + Enter 可切换到文件传输助手",
        "scripts/send_queue_uia_test.py 验证 clipboard_alt_s 可发送并在可见消息中确认",
        "本机 dump 验证 input_box 的 Name 等于当前聊天名，可作为 chat_title 临时不可读时的身份兜底",
    ],
    "window": {
        "title_contains": "微信",
        "class_name": "WeChatMainWndForPC",
        "automation_id": "",
    },
    "switch_conversation": {
        "verified": True,
        "method": "ctrl_f_search_enter",
        "fallback": "Ctrl+F 后焦点未落到已验证 search_box 时失败，不继续输入，避免误发到聊天输入框。",
    },
    "chat_title": {
        "control_type": "TextControl",
        "name_not_empty": True,
        "region": "chat_header",
        "name_not_matches": r"^(\d{4}年|星期.|\d{1,2}:\d{2}|.*\bAM\b|.*\bPM\b)",
        "max_width_ratio": 0.35,
        "fallback": "失败时 dump 当前聊天窗口 header 区域",
    },
    "search_box": {
        "control_type": "EditControl",
        "name_contains": "搜索",
        "region": "conversation_panel_header",
        "fallback": "失败时 dump 左侧会话面板顶部",
    },
    "conversation_list": {
        "control_type": "ListControl",
        "name_contains": "会话",
        "region": "conversation_panel",
        "fallback": "失败时 dump 左侧会话列表",
    },
    "navigation_avatar": {
        "control_type": "ButtonControl",
        "region": "navigation_top",
        "name_not_empty": True,
        "fallback": "失败时只影响 self/other 自动识别，不影响发送后按内容验证。",
    },
    "message_list": {
        "control_type": "ListControl",
        "name_contains": "消息",
        "region": "message_area",
        "fallback": "失败时 dump 右侧消息区域",
    },
    "message_item": {
        "self_avatar_region": "right",
        "friend_unknown_text_as_other": True,
        "system_text_patterns": [
            r"^以下[为是]新消息$",
            r"撤回了一条消息",
            r"你已添加了.*现在可以开始聊天了",
            r"对方开启了朋友验证",
        ],
        "fallback": "私聊中非 self/system 文本按 other 处理；群聊不启用该规则。新增系统提示样式时补充 system_text_patterns。",
    },
    "input_box": {
        "control_type": "EditControl",
        "region": "input_area",
        "fallback": "失败时 dump 右侧底部输入区",
    },
    "send_button": {
        "control_type": "ButtonControl",
        "name_contains": "发送(S)",
        "region": "input_area",
        "fallback": "失败时停止，不循环兜底",
    },
    "send_behavior": {
        "method": "clipboard_alt_s",
        "fallback_order": [],
        "note": "单一无鼠标策略；不循环兜底，避免向输入框重复写入文本。",
        "verify_after_send": True,
    },
}


def builtin_locators() -> dict[str, Any]:
    return deepcopy(WECHAT_391256_BUILTIN_LOCATORS)
