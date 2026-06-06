from fastapi.testclient import TestClient

from wx_ai_assistant.domain.enums import SendTaskStatus


def build_client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DRIVER_MODE", "mock")
    monkeypatch.setenv("APP_AI_MODE", "echo")
    monkeypatch.setenv("APP_AI_CONFIG", str(tmp_path / "missing_ai.local.env"))
    monkeypatch.setenv("APP_AI_API_KEY", "")
    monkeypatch.setenv("APP_AUTO_SEND_ENABLED", "false")
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("APP_HISTORY_DB_PATH", str(tmp_path / "history.sqlite3"))
    from wx_ai_assistant.main import create_app

    return TestClient(create_app())


def test_api_friend_only_send_task_query_and_poll_once(tmp_path, monkeypatch):
    with build_client(tmp_path, monkeypatch) as client:
        group_response = client.post(
            "/listen/targets",
            json={"display_name": "测试群", "conversation_type": "group", "local_id": "group1"},
        )
        assert group_response.status_code == 400

        response = client.post(
            "/listen/targets",
            json={"display_name": "文件传输助手", "conversation_type": "friend", "local_id": "filehelper"},
        )
        assert response.status_code == 200
        conversation_id = response.json()["data"]["conversation"]["conversation_id"]

        response = client.post("/listen/poll-once")
        assert response.status_code == 200

        response = client.post("/send/text", json={"conversation_id": conversation_id, "content": "hello"})
        assert response.status_code == 200
        send_task_id = response.json()["data"]["send_task_id"]

        response = client.get("/send/tasks", params={"status": "pending"})
        assert response.status_code == 200
        assert [task["send_task_id"] for task in response.json()["data"]] == [send_task_id]

        response = client.get(f"/send/tasks/{send_task_id}")
        assert response.status_code == 200
        assert response.json()["data"]["content"] == "hello"

        client.app.state.repo.update_send_task(send_task_id, SendTaskStatus.FAILED, "focus failed")
        response = client.post(f"/send/tasks/{send_task_id}/retry")
        assert response.status_code == 200
        assert response.json()["data"]["kind"] == "retry_send_task"
        assert response.json()["data"]["status"] in {"queued", "running", "success"}

        response = client.get("/system/current-conversation")
        assert response.status_code == 200

        response = client.get("/system/diagnostics")
        assert response.status_code == 200
        diagnostics = response.json()["data"]
        assert diagnostics["settings"]["ai_api_key_configured"] is False
        assert "send_task_counts" in diagnostics
        assert "runtime_worker" in diagnostics


def test_admin_page_and_overview_api(tmp_path, monkeypatch):
    nodes_path = tmp_path / "langgraph_nodes.local.json"
    nodes_example_path = tmp_path / "langgraph_nodes.local.example.json"
    nodes_path.write_text("{}", encoding="utf-8")
    nodes_example_path.write_text('{"reply_strategy":{"default_max_messages":2}}', encoding="utf-8")
    monkeypatch.setenv("APP_LANGGRAPH_NODES_PATH", str(nodes_path))
    with build_client(tmp_path, monkeypatch) as client:
        page = client.get("/admin")
        assert page.status_code == 200
        assert "ChatWe 本地控制台" in page.text

        target = client.post(
            "/listen/targets",
            json={"display_name": "AAxc", "conversation_type": "friend", "local_id": "AAxc"},
        ).json()["data"]
        conversation_id = target["conversation"]["conversation_id"]
        client.post(
            "/messages/mock/text",
            json={"conversation_id": conversation_id, "content": "你好", "sender_name": "friend"},
        )

        overview = client.get("/admin-api/overview")
        assert overview.status_code == 200
        data = overview.json()["data"]
        assert data["targets"][0]["conversation"]["display_name"] == "AAxc"
        assert data["messages_by_target"][conversation_id][-1]["content"] == "你好"

        config = client.get("/admin-api/config")
        assert config.status_code == 200
        assert "api_key_configured" in config.json()["data"]
        assert "extra_body" in config.json()["data"]
        assert config.json()["data"]["auto_send_enabled"] is False
        assert "vision_enabled" in config.json()["data"]
        assert "speech_enabled" in config.json()["data"]
        assert "reply_strategy" in config.json()["data"]["langgraph_nodes_json"]

        updated = client.post(
            "/admin-api/config",
            json={
                "vision_enabled": True,
                "auto_send_enabled": True,
                "vision_base_url": "https://vision.example/v1",
                "vision_model": "vision-model",
                "vision_api_key": "sk-vision",
                "speech_enabled": True,
                "speech_base_url": "https://speech.example/v1",
                "speech_model": "speech-model",
                "speech_api_key": "sk-speech",
                "speech_language": "zh",
            },
        )
        assert updated.status_code == 200
        env_text = (tmp_path / "missing_ai.local.env").read_text(encoding="utf-8")
        assert "APP_AUTO_SEND_ENABLED=true" in env_text
        assert "APP_SPEECH_AI_ENABLED=true" in env_text
        assert "APP_SPEECH_AI_API_KEY=sk-speech" in env_text

        bad_extra_body = client.post("/admin-api/config", json={"extra_body": "[]"})
        assert bad_extra_body.status_code == 400
        assert "APP_AI_EXTRA_BODY" in bad_extra_body.json()["detail"]

        cleared = client.post(f"/admin-api/conversations/{conversation_id}/clear-memory")
        assert cleared.status_code == 200
        assert cleared.json()["data"]["messages"] >= 1


def test_contact_config_feature_is_cancelled(tmp_path, monkeypatch):
    with build_client(tmp_path, monkeypatch) as client:
        target = client.post(
            "/listen/targets",
            json={"display_name": "AAxc", "conversation_type": "friend", "local_id": "AAxc"},
        ).json()["data"]
        conversation_id = target["conversation"]["conversation_id"]

        response = client.post(
            f"/admin-api/contact-configs/{conversation_id}/natural-language",
            json={"instruction": "这个联系人轻度主动，可甜可冷，最多两条，少追问，涉及钱要冷一点", "proactive_mode": "light"},
        )

        assert response.status_code == 404

        configs = client.get("/admin-api/contact-configs")
        assert configs.status_code == 404


def test_web_status_and_commands_do_not_call_driver_directly(tmp_path, monkeypatch):
    with build_client(tmp_path, monkeypatch) as client:
        target = client.post(
            "/listen/targets",
            json={"display_name": "AAxc", "conversation_type": "friend", "local_id": "AAxc"},
        ).json()["data"]
        conversation_id = target["conversation"]["conversation_id"]
        task = client.post("/send/text", json={"conversation_id": conversation_id, "content": "hello"}).json()["data"]
        client.app.state.repo.update_send_task(task["send_task_id"], SendTaskStatus.FAILED, "focus failed")

        client.app.state.runtime_worker.stop()

        def fail_driver_call(*args, **kwargs):
            raise AssertionError("web/API request must not call WeChat driver directly")

        client.app.state.driver.status = fail_driver_call
        client.app.state.driver.get_current_conversation = fail_driver_call
        client.app.state.driver.switch_conversation = fail_driver_call

        assert client.get("/admin-api/overview").status_code == 200
        assert client.get("/system/current-conversation").status_code == 200
        assert client.post(f"/listen/targets/{conversation_id}/start").status_code == 200
        retry = client.post(f"/send/tasks/{task['send_task_id']}/retry")
        assert retry.status_code == 200
        assert retry.json()["data"]["kind"] == "retry_send_task"
