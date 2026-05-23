from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.application.app_service import WechatApplicationService  # noqa: E402
from wx_ai_assistant.application.context_builder import ContextBuilder  # noqa: E402
from wx_ai_assistant.application.listener_manager import ListenerManager  # noqa: E402
from wx_ai_assistant.application.message_ingestion import MessageIngestionService  # noqa: E402
from wx_ai_assistant.application.send_queue import SendQueue  # noqa: E402
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus  # noqa: E402
from wx_ai_assistant.domain.models import ListenTarget  # noqa: E402
from wx_ai_assistant.identity.verifier import ConversationVerifier  # noqa: E402
from wx_ai_assistant.infrastructure.ai.dummy_ai import EchoAiGateway  # noqa: E402
from wx_ai_assistant.infrastructure.history.normalized_sqlite_history_reader import NormalizedSqliteHistoryReader  # noqa: E402
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "文件传输助手"
    polls = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    repo_path = Path(tempfile.gettempdir()) / "wechat_ai_uia_listener_poll_once.sqlite3"
    history_path = Path(tempfile.gettempdir()) / "wechat_ai_uia_listener_history.sqlite3"
    repo_path.unlink(missing_ok=True)
    history_path.unlink(missing_ok=True)

    repo = SqliteRepository(repo_path)
    repo.initialize_schema()
    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    verifier = ConversationVerifier()
    ingestion = MessageIngestionService(repo, driver, verifier)
    context_builder = ContextBuilder(repo, NormalizedSqliteHistoryReader(history_path))
    send_queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message, driver_lock=threading.RLock())
    app_service = WechatApplicationService(repo, driver, ingestion, context_builder, EchoAiGateway(), send_queue)
    target_model = app_service.add_listen_target(target, ConversationType.FRIEND, remark_name=target, local_id=target)
    repo.set_listen_status(target_model.conversation.conversation_id, ListenStatus.LISTENING)

    listener = ListenerManager(
        repo=repo,
        driver=driver,
        poll_interval_seconds=1.0,
        on_messages=app_service.handle_realtime_messages,
        driver_lock=threading.RLock(),
    )
    counts: list[int] = []
    for index in range(polls):
        listener.poll_once()
        count = len(repo.list_recent_messages(target_model.conversation.conversation_id, 200))
        counts.append(count)
        print(f"poll={index + 1} stored_messages={count}")

    target_after = repo.get_listen_target(target_model.conversation.conversation_id)
    messages = repo.list_recent_messages(target_model.conversation.conversation_id, 30)
    pending = repo.list_pending_send_tasks(limit=20)

    print(f"listen_status={target_after.status.value if target_after else None} error={target_after.last_error if target_after else None}")
    print(f"stored_messages={len(messages)}")
    print(f"stored_message_counts={counts}")
    for msg in messages[-10:]:
        print(f"message sender={msg.sender_type.value} source={msg.source.value} content={msg.content!r}")
    print(f"pending_send_tasks={len(pending)}")
    for task in pending:
        print(f"pending_task id={task.send_task_id} content={task.content!r} trigger={task.trigger_message_id}")

    return 0 if target_after and target_after.status == ListenStatus.LISTENING else 3


if __name__ == "__main__":
    raise SystemExit(main())
