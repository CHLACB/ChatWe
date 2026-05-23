from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import uvicorn

from wx_ai_assistant.domain.enums import ConversationType
from wx_ai_assistant.domain.models import ConversationIdentity
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver


def _line(status: str, name: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"{status:4} {name}{suffix}")


def _describe(control: object) -> str:
    return (
        f"name={getattr(control, 'Name', '')!r} "
        f"type={getattr(control, 'ControlTypeName', '')!r} "
        f"rect={getattr(control, 'BoundingRectangle', '')!r}"
    )


def run_api(args: argparse.Namespace) -> int:
    from wx_ai_assistant.main import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )
    return 0


def run_selfcheck(args: argparse.Namespace) -> int:
    driver = UiaWechatDriver(Path(args.locators))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    failed = False
    for key in ["navigation_avatar", "search_box", "conversation_list", "chat_title", "message_list", "input_box", "send_button"]:
        try:
            control = driver._locate_required(key)
            _line("OK", key, _describe(control))
        except Exception as exc:
            failed = True
            _line("FAIL", key, str(exc))

    try:
        search_box = driver._locate_required("search_box")
        focused = driver._focus_search_box_with_hotkey(search_box)
        if focused is not None:
            _line("OK", "ctrl_f_focus", _describe(focused))
        else:
            failed = True
            _line("FAIL", "ctrl_f_focus", "focused=None")
    except Exception as exc:
        failed = True
        _line("FAIL", "ctrl_f_focus", str(exc))

    identity = ConversationIdentity(
        conversation_id="selfcheck_target",
        conversation_type=ConversationType.FRIEND,
        display_name=args.target,
        remark_name=args.target,
        local_id=args.target,
    )
    switch_status = driver.switch_conversation(identity)
    if switch_status.ok:
        _line("OK", "switch_conversation", switch_status.message)
    else:
        failed = True
        _line("FAIL", "switch_conversation", switch_status.message)

    current = driver.get_current_conversation()
    _line("INFO", "current_conversation", repr(current))

    try:
        messages = driver.read_visible_text_messages(identity)
        _line("OK", "read_visible_messages", f"count={len(messages)}")
        for msg in messages[-5:]:
            print(f"     {msg.sender_type.value:7} {msg.message_type.value:5} {msg.content!r}")
    except Exception as exc:
        failed = True
        _line("FAIL", "read_visible_messages", str(exc))

    time.sleep(0.1)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ChatWe")
    subparsers = parser.add_subparsers(dest="command", required=True)

    api = subparsers.add_parser("api", help="Start FastAPI service")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--log-level", default="info")
    api.set_defaults(func=run_api)

    selfcheck = subparsers.add_parser("selfcheck", help="Run WeChat UIA self-check")
    selfcheck.add_argument("target", nargs="?", default="文件传输助手")
    selfcheck.add_argument("--locators", default="config/wechat_locators.local.json")
    selfcheck.set_defaults(func=run_selfcheck)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
