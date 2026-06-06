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


def test_ai_decision_log_exposes_observable_state_fields(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    repo = SqliteRepository(db_path)
    repo.initialize_schema()
    repo.save_ai_decision_log(
        AiDecisionLog(
            run_id="lg_observable",
            conversation_id="conv_a",
            trigger_message_id="msg_a",
            trigger_message="转账给你吗",
            display_name="AAxc",
            contact_policy={"name": "default"},
            conversation_profile={"relationship": "熟人"},
            intent="钱款确认",
            should_reply=True,
            draft_messages=["先别转"],
            final_messages=["先别转"],
            raw_state_json={
                "risk_flags": ["转账"],
                "requires_safety_model": True,
                "media_observations": ["无媒体"],
                "retrieved_memories": ["历史摘要：一起测试"],
                "node_settings": {"semantic": {"recent_message_limit": 3}},
            },
        )
    )

    rows = repo.list_ai_decision_logs(run_id="lg_observable")

    assert rows[0]["risk_flags"] == ["转账"]
    assert rows[0]["requires_safety_model"] is True
    assert rows[0]["retrieved_memories"] == ["历史摘要：一起测试"]
    assert rows[0]["node_settings"]["semantic"]["recent_message_limit"] == 3
