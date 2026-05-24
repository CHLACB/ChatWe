from __future__ import annotations

import argparse
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.core.config import load_settings  # noqa: E402
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus  # noqa: E402
from wx_ai_assistant.domain.models import ConversationIdentity, ListenTarget  # noqa: E402
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage listen targets without opening a GUI.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="新增监听对象，默认未监听")
    add.add_argument("display_name")
    add.add_argument("--remark-name", default=None)
    add.add_argument("--local-id", default=None)
    add.add_argument("--start", action="store_true", help="新增后直接标记为 listening")

    sub.add_parser("list", help="列出监听对象")

    start = sub.add_parser("start", help="启动监听对象")
    start.add_argument("conversation_id")

    stop = sub.add_parser("stop", help="停止监听对象")
    stop.add_argument("conversation_id")

    delete = sub.add_parser("delete", help="删除监听对象")
    delete.add_argument("conversation_id")

    args = parser.parse_args()
    settings = load_settings()
    repo = SqliteRepository(settings.db_path)
    repo.initialize_schema()

    if args.command == "add":
        identity = _identity(args.display_name, args.remark_name, args.local_id)
        status = ListenStatus.LISTENING if args.start else ListenStatus.STOPPED
        repo.upsert_listen_target(ListenTarget(conversation=identity, status=status))
        print(f"conversation_id={identity.conversation_id} status={status.value} display_name={identity.display_name}")
        return 0
    if args.command == "list":
        for target in repo.list_listen_targets():
            print(
                f"{target.conversation.conversation_id}\t"
                f"{target.status.value}\t"
                f"{target.conversation.display_name}\t"
                f"error={target.last_error or ''}"
            )
        return 0
    if args.command == "start":
        repo.set_listen_status(args.conversation_id, ListenStatus.LISTENING, None)
        print(f"started {args.conversation_id}")
        return 0
    if args.command == "stop":
        repo.set_listen_status(args.conversation_id, ListenStatus.STOPPED, "manual stop")
        print(f"stopped {args.conversation_id}")
        return 0
    if args.command == "delete":
        deleted = repo.delete_listen_target(args.conversation_id)
        print(f"deleted={deleted} {args.conversation_id}")
        return 0 if deleted else 2
    return 1


def _identity(display_name: str, remark_name: str | None, local_id: str | None) -> ConversationIdentity:
    conversation_type = ConversationType.FRIEND
    stable = f"{conversation_type.value}|{local_id or ''}|{remark_name or ''}|{display_name}"
    return ConversationIdentity(
        conversation_id="conv_" + uuid5(NAMESPACE_URL, stable).hex,
        conversation_type=conversation_type,
        display_name=display_name,
        remark_name=remark_name,
        local_id=local_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
