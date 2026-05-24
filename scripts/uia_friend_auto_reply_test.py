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
from wx_ai_assistant.application.ai_turn import AiTurnParser  # noqa: E402
from wx_ai_assistant.application.context_builder import ContextBuilder  # noqa: E402
from wx_ai_assistant.application.listener_manager import ListenerManager  # noqa: E402
from wx_ai_assistant.application.message_ingestion import MessageIngestionService  # noqa: E402
from wx_ai_assistant.application.send_queue import SendQueue  # noqa: E402
from wx_ai_assistant.core.config import load_settings  # noqa: E402
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus, SendTaskStatus  # noqa: E402
from wx_ai_assistant.identity.verifier import ConversationVerifier  # noqa: E402
from wx_ai_assistant.infrastructure.ai.factory import build_ai_gateway  # noqa: E402
from wx_ai_assistant.infrastructure.history.normalized_sqlite_history_reader import NormalizedSqliteHistoryReader  # noqa: E402
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for one new friend message, generate AI reply, and send through the queue.")
    parser.add_argument("target", help="好友私聊名称，例如 AAxc")
    parser.add_argument("--timeout", type=float, default=180.0, help="等待新消息秒数")
    parser.add_argument("--interval", type=float, default=1.5, help="轮询间隔秒数")
    parser.add_argument("--ai-mode", default=None, help="覆盖 APP_AI_MODE，例如 echo/openai_compatible")
    args = parser.parse_args()

    settings = load_settings()
    repo_path = Path(tempfile.gettempdir()) / "wechat_ai_friend_auto_reply_test.sqlite3"
    history_path = Path(tempfile.gettempdir()) / "wechat_ai_friend_auto_reply_history.sqlite3"
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
    service = WechatApplicationService(
        repo,
        driver,
        ingestion,
        context_builder,
        build_ai_gateway(settings, force_mode=args.ai_mode),
        send_queue,
        AiTurnParser(max_messages=settings.ai_max_messages_per_turn, strict_json=settings.ai_strict_turn_json),
        ai_turn_quiet_seconds=settings.ai_turn_quiet_seconds,
    )
    send_queue.on_failed = lambda conversation_id, error: repo.set_listen_status(conversation_id, ListenStatus.STOPPED, error)
    target = service.add_listen_target(args.target, ConversationType.FRIEND, remark_name=args.target, local_id=args.target)
    repo.set_listen_status(target.conversation.conversation_id, ListenStatus.LISTENING)
    listener = ListenerManager(
        repo=repo,
        driver=driver,
        poll_interval_seconds=args.interval,
        on_messages=service.handle_realtime_messages,
        on_baseline_messages=service.handle_baseline_messages,
        on_after_poll=service.flush_ready_ai_turns,
        driver_lock=driver_lock,
    )

    print(f"ai_mode={args.ai_mode or settings.ai_mode} model={settings.ai_model} api_key_configured={bool(settings.ai_api_key)}")
    print("baseline_poll=begin")
    listener.poll_once()
    baseline_count = len(repo.list_recent_messages(target.conversation.conversation_id, 500))
    print(f"baseline_poll=done stored_messages={baseline_count}")
    print("请现在让该好友发送一条新的文本消息；脚本会等待、生成回复，并通过发送队列发送。")

    send_queue.start()
    deadline = time.time() + args.timeout
    seen_task_ids: set[str] = set()
    try:
        while time.time() < deadline:
            listener.poll_once()
            target_after = repo.get_listen_target(target.conversation.conversation_id)
            if target_after and target_after.status != ListenStatus.LISTENING:
                print(f"listen_status={target_after.status.value} error={target_after.last_error}")
                return 3

            tasks = repo.list_send_tasks(conversation_id=target.conversation.conversation_id, limit=20)
            new_tasks = [task for task in tasks if task.send_task_id not in seen_task_ids]
            for task in reversed(new_tasks):
                seen_task_ids.add(task.send_task_id)
                print(f"task_created id={task.send_task_id} status={task.status.value} content={task.content!r}")

            terminal = [task for task in tasks if task.status in {SendTaskStatus.SUCCESS, SendTaskStatus.FAILED}]
            if terminal:
                for task in reversed(terminal[:5]):
                    print(f"task_final id={task.send_task_id} status={task.status.value} error={task.error_message}")
                return 0 if any(task.status == SendTaskStatus.SUCCESS for task in terminal) else 4

            time.sleep(args.interval)
    finally:
        send_queue.stop()

    print("timeout=没有等到新的好友文本消息或发送任务")
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
