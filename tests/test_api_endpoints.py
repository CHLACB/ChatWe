from fastapi.testclient import TestClient


def build_client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DRIVER_MODE", "mock")
    monkeypatch.setenv("APP_AI_MODE", "echo")
    monkeypatch.setenv("APP_AI_CONFIG", str(tmp_path / "missing_ai.local.env"))
    monkeypatch.setenv("APP_AI_API_KEY", "")
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

        response = client.get("/system/current-conversation")
        assert response.status_code == 200

        response = client.get("/system/diagnostics")
        assert response.status_code == 200
        diagnostics = response.json()["data"]
        assert diagnostics["settings"]["ai_api_key_configured"] is False
        assert "send_task_counts" in diagnostics


def test_admin_page_and_overview_api(tmp_path, monkeypatch):
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

        cleared = client.post(f"/admin-api/conversations/{conversation_id}/clear-memory")
        assert cleared.status_code == 200
        assert cleared.json()["data"]["messages"] >= 1
