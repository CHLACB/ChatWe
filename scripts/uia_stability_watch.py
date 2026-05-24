from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.application.app_service import WechatApplicationService  # noqa: E402
from wx_ai_assistant.application.context_builder import ContextBuilder  # noqa: E402
from wx_ai_assistant.application.listener_manager import ListenerManager  # noqa: E402
from wx_ai_assistant.application.message_ingestion import MessageIngestionService  # noqa: E402
from wx_ai_assistant.application.send_queue import SendQueue  # noqa: E402
from wx_ai_assistant.core.config import load_settings  # noqa: E402
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus  # noqa: E402
from wx_ai_assistant.identity.verifier import ConversationVerifier  # noqa: E402
from wx_ai_assistant.infrastructure.ai.dummy_ai import DummyAiGateway  # noqa: E402
from wx_ai_assistant.infrastructure.history.normalized_sqlite_history_reader import NormalizedSqliteHistoryReader  # noqa: E402
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Long-run UIA listener stability watch. It never sends AI replies.")
    parser.add_argument("target", help="好友私聊名称")
    parser.add_argument("--minutes", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()

    settings = load_settings()
    repo_path = Path(tempfile.gettempdir()) / "wechat_ai_uia_stability_watch.sqlite3"
    history_path = Path(tempfile.gettempdir()) / "wechat_ai_uia_stability_history.sqlite3"
    repo_path.unlink(missing_ok=True)
    history_path.unlink(missing_ok=True)

    repo = SqliteRepository(repo_path)
    repo.initialize_schema()
    driver = UiaWechatDriver(settings.wechat_locators)
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    verifier = ConversationVerifier()
    ingestion = MessageIngestionService(repo, driver, verifier)
    context_builder = ContextBuilder(repo, NormalizedSqliteHistoryReader(history_path))
    driver_lock = threading.RLock()
    send_queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message, driver_lock=driver_lock)
    service = WechatApplicationService(repo, driver, ingestion, context_builder, DummyAiGateway(), send_queue)
    target = service.add_listen_target(args.target, ConversationType.FRIEND, remark_name=args.target, local_id=args.target)
    repo.set_listen_status(target.conversation.conversation_id, ListenStatus.LISTENING)
    listener = ListenerManager(
        repo=repo,
        driver=driver,
        poll_interval_seconds=args.interval,
        on_messages=service.handle_realtime_messages,
        on_baseline_messages=service.handle_baseline_messages,
        driver_lock=driver_lock,
    )

    deadline = time.time() + args.minutes * 60
    polls = 0
    last_count = 0
    while time.time() < deadline:
        started = time.time()
        listener.poll_once()
        polls += 1
        target_after = repo.get_listen_target(target.conversation.conversation_id)
        messages = repo.list_recent_messages(target.conversation.conversation_id, 500)
        current = driver.get_current_conversation()
        print(
            "poll={polls} status={status} messages={messages} delta={delta} current={current!r} elapsed={elapsed:.2f}s".format(
                polls=polls,
                status=target_after.status.value if target_after else None,
                messages=len(messages),
                delta=len(messages) - last_count,
                current=current.display_name if current else None,
                elapsed=time.time() - started,
            )
        )
        last_count = len(messages)
        if target_after and target_after.status != ListenStatus.LISTENING:
            print(f"stopped error={target_after.last_error}")
            return 3
        time.sleep(args.interval)

    print(f"completed polls={polls} minutes={args.minutes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
