from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.application.message_ingestion import MessageIngestionService  # noqa: E402
from wx_ai_assistant.application.send_queue import SendQueue  # noqa: E402
from wx_ai_assistant.domain.enums import ConversationType  # noqa: E402
from wx_ai_assistant.domain.models import ConversationIdentity, ListenTarget  # noqa: E402
from wx_ai_assistant.identity.verifier import ConversationVerifier  # noqa: E402
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else f"uia-queue-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    identity = ConversationIdentity(
        conversation_id="conv_filehelper_uia_queue",
        conversation_type=ConversationType.FRIEND,
        display_name="文件传输助手",
        remark_name="文件传输助手",
        local_id="filehelper",
    )

    repo_path = Path(tempfile.gettempdir()) / "wechat_ai_filehelper_queue_test.sqlite3"
    repo = SqliteRepository(repo_path)
    repo.initialize_schema()
    repo.upsert_listen_target(ListenTarget(conversation=identity))

    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    verifier = ConversationVerifier()
    ingestion = MessageIngestionService(repo, driver, verifier)
    queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message)
    task = queue.enqueue(identity.conversation_id, text)
    print(f"queued_task={task.send_task_id} content={text!r}")

    queue._process(task)
    row = repo._conn.execute("SELECT status, error_message FROM send_tasks WHERE send_task_id=?", (task.send_task_id,)).fetchone()
    print(f"send_method={driver.last_send_method}")
    print(f"send_task_status={row['status']} error={row['error_message']}")
    for message in repo.list_recent_messages(identity.conversation_id, 10):
        print(f"stored_message sender={message.sender_type.value} source={message.source.value} content={message.content!r}")
    return 0 if row["status"] == "success" else 4


if __name__ == "__main__":
    raise SystemExit(main())
