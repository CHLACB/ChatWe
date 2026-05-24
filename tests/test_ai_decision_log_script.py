import subprocess
import sys

from wx_ai_assistant.domain.models import AiDecisionLog
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository


def test_show_ai_decision_logs_script_outputs_run_id(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    repo = SqliteRepository(db_path)
    repo.initialize_schema()
    repo.save_ai_decision_log(
        AiDecisionLog(
            run_id="lg_script_test",
            conversation_id="conv_a",
            trigger_message_id="msg_a",
            trigger_message="你有空吗",
            display_name="AAxc",
            contact_policy={"name": "default"},
            conversation_profile={"relationship": "熟人"},
            intent="问是否有空",
            emotion="neutral",
            should_reply=True,
            reply_strategy="简短确认",
            draft_messages=["有空"],
            safety_action="allow",
            final_messages=["有空"],
            raw_state={"run_id": "lg_script_test"},
            raw_state_json={"run_id": "lg_script_test"},
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/show_ai_decision_logs.py",
            "--db-path",
            str(db_path),
            "--run-id",
            "lg_script_test",
        ],
        cwd=".",
        text=True,
        capture_output=True,
        check=True,
    )

    assert "lg_script_test" in result.stdout
    assert "问是否有空" in result.stdout
