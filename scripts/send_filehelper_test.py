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
from wx_ai_assistant.domain.models import ConversationIdentity  # noqa: E402
from wx_ai_assistant.identity.verifier import ConversationVerifier  # noqa: E402
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else f"uia-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    identity = ConversationIdentity(
        conversation_id="conv_filehelper_uia_test",
        conversation_type=ConversationType.FRIEND,
        display_name="文件传输助手",
        remark_name="文件传输助手",
        local_id="filehelper",
    )

    repo_path = Path(tempfile.gettempdir()) / "wechat_ai_filehelper_send_test.sqlite3"
    repo = SqliteRepository(repo_path)
    repo.initialize_schema()
    repo.upsert_conversation(identity)

    driver = UiaWechatDriver(Path("config/wechat_locators.local.json"))
    status = driver.initialize()
    print(status)
    if not status.ok:
        return 2

    current = driver.get_current_conversation()
    print(f"current_before={current}")
    if current is None:
        print("chat_title diagnostic:")
        locator = (driver._locators or {}).get("chat_title") or {}
        try:
            control = driver._locate_required("chat_title")
            print(
                "  located "
                f"name={getattr(control, 'Name', '')!r} "
                f"type={getattr(control, 'ControlTypeName', '')!r} "
                f"rect={getattr(control, 'BoundingRectangle', '')!r}"
            )
        except Exception as exc:
            print(f"  locate failed: {exc}")
            for control in driver._iter_controls(driver._window):
                if driver._matches(control, locator):
                    print(
                        "  candidate "
                        f"name={getattr(control, 'Name', '')!r} "
                        f"type={getattr(control, 'ControlTypeName', '')!r} "
                        f"rect={getattr(control, 'BoundingRectangle', '')!r}"
                    )
    verifier = ConversationVerifier()
    result = verifier.identity_matches(identity, current)
    if not result.ok:
        print(f"ABORT: 当前会话不是文件传输助手: {result.reason}")
        return 3

    ingestion = MessageIngestionService(repo, driver, verifier)
    queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message)
    task = queue.enqueue(identity.conversation_id, text)
    queue._process(task)  # Diagnostic synchronous queue execution.

    row = repo._conn.execute("SELECT status, error_message FROM send_tasks WHERE send_task_id=?", (task.send_task_id,)).fetchone()
    print(f"send_method={driver.last_send_method}")
    print(f"send_task_status={row['status']} error={row['error_message']}")
    for message in repo.list_recent_messages(identity.conversation_id, 5):
        print(f"stored_message sender={message.sender_type} content={message.content!r}")
    return 0 if row["status"] == "success" else 4


if __name__ == "__main__":
    raise SystemExit(main())
