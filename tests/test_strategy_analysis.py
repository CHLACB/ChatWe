from fastapi.testclient import TestClient
import base64
import hashlib
import math
from io import BytesIO
from zipfile import ZipFile

from wx_ai_assistant.application.strategy_analysis import StrategyAnalysisReport


def build_client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DRIVER_MODE", "mock")
    monkeypatch.setenv("APP_AI_MODE", "echo")
    monkeypatch.setenv("APP_AI_CONFIG", str(tmp_path / "missing_ai.local.env"))
    monkeypatch.setenv("APP_AI_API_KEY", "")
    monkeypatch.setenv("APP_EMBEDDING_API_KEY", "")
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "strategy.sqlite3"))
    monkeypatch.setenv("APP_HISTORY_DB_PATH", str(tmp_path / "history.sqlite3"))
    from wx_ai_assistant.application import strategy_analysis

    monkeypatch.setattr(strategy_analysis.DashScopeMultimodalTextEmbeddingProvider, "embed", _fake_embed)
    from wx_ai_assistant.main import create_app

    return TestClient(create_app())


def test_strategy_analysis_knowledge_search_and_conversation_report(tmp_path, monkeypatch):
    with build_client(tmp_path, monkeypatch) as client:
        class FakeAnalyzer:
            def analyze(self, identity, messages, instruction, knowledge, user_direction=""):
                return StrategyAnalysisReport(
                    conversation={
                        "conversation_id": identity.conversation_id,
                        "conversation_type": identity.conversation_type,
                        "display_name": identity.display_name,
                        "remark_name": identity.remark_name,
                        "local_id": identity.local_id,
                        "last_verified_at": identity.last_verified_at,
                    },
                    message_count=len(messages),
                    instruction=instruction,
                    intent="大模型分析的意图",
                    needs=["降低不确定感"],
                    relationship_signal="大模型分析的关系信号",
                    risks=["不要催促"],
                    suggested_strategy=f"参考 {knowledge[0].title} 后短句承接",
                    reply_examples=["我明白，你先按舒服的节奏来。"],
                    matched_knowledge=[
                        {
                            "chunk_id": chunk.chunk_id,
                            "document_id": chunk.document_id,
                            "title": chunk.title,
                            "source_type": chunk.source_type,
                            "tags": chunk.tags,
                            "knowledge_type": chunk.knowledge_type,
                            "chunk_text": chunk.chunk_text,
                            "chunk_index": chunk.chunk_index,
                            "score": chunk.score,
                            "created_at": chunk.created_at.isoformat(),
                        }
                        for chunk in knowledge
                    ],
                    no_send=True,
                    user_direction=user_direction,
                )

        client.app.state.strategy_analysis_service.analyzer = FakeAnalyzer()
        target = client.post(
            "/listen/targets",
            json={"display_name": "A1", "conversation_type": "friend", "local_id": "A1"},
        ).json()["data"]
        conversation_id = target["conversation"]["conversation_id"]

        document = client.post(
            "/strategy-analysis/documents/text",
            json={
                "title": "私聊回复策略",
                "knowledge_type": "strategy",
                "tags": ["私聊", "节奏"],
                "content": "对方担心或犹豫时，不要催促。先确认顾虑，回复要短，给对方空间。",
            },
        )
        assert document.status_code == 200
        assert document.json()["data"]["chunk_count"] == 1
        assert document.json()["data"]["vector_entry"]["enabled"] is True
        assert document.json()["data"]["vector_entry"]["backend"] == "sqlite_cosine"
        assert document.json()["data"]["vector_entry"]["indexed_count"] == 1

        search = client.post("/strategy-analysis/knowledge/search", json={"query": "对方担心 不要催促", "limit": 3})
        assert search.status_code == 200
        search_data = search.json()["data"]
        assert search_data["retriever"] == "hybrid_vector_lexical"
        assert search_data["vector_entry"]["enabled"] is True
        assert search_data["matches"][0]["title"] == "私聊回复策略"
        assert search_data["matches"][0]["score"] > 0
        assert search_data["matches"][0]["score_source"] in {"vector", "lexical", "hybrid"}
        assert "vector_score" in search_data["matches"][0]
        assert "lexical_score" in search_data["matches"][0]

        second = client.post(
            "/strategy-analysis/documents/text",
            json={
                "title": "无关文档",
                "knowledge_type": "默认",
                "tags": ["无关"],
                "content": "天气很好，今天适合整理文件和打扫房间。",
            },
        ).json()["data"]["document"]
        scoped = client.post(
            "/strategy-analysis/knowledge/search",
            json={
                "query": "天气 打扫",
                "limit": 5,
                "document_ids": [document.json()["data"]["document"]["document_id"]],
            },
        )
        assert scoped.status_code == 200
        scoped_data = scoped.json()["data"]
        assert scoped_data["vector_entry"]["document_filter_count"] == 1
        assert all(match["document_id"] != second["document_id"] for match in scoped_data["matches"])

        client.post(
            "/messages/mock/text",
            json={"conversation_id": conversation_id, "content": "这个靠谱吗，我有点担心", "sender_name": "friend"},
        )

        report = client.post(
            f"/strategy-analysis/conversations/{conversation_id}/analyze",
            json={
                "instruction": "分析对方需求和回复策略",
                "user_direction": "这轮优先安抚，不推进邀约",
                "message_limit": 20,
                "knowledge_limit": 3,
            },
        )
        assert report.status_code == 200
        data = report.json()["data"]
        assert data["conversation"]["display_name"] == "A1"
        assert data["no_send"] is True
        assert data["user_direction"] == "这轮优先安抚，不推进邀约"
        assert "降低不确定感" in data["needs"]
        assert data["matched_knowledge"]


def test_strategy_config_draft_endpoint_is_cancelled(tmp_path, monkeypatch):
    with build_client(tmp_path, monkeypatch) as client:
        target = client.post(
            "/listen/targets",
            json={"display_name": "A2", "conversation_type": "friend", "local_id": "A2"},
        ).json()["data"]
        conversation_id = target["conversation"]["conversation_id"]

        draft = client.post(
            f"/strategy-analysis/conversations/{conversation_id}/config-draft",
            json={"instruction": "这个联系人别主动，回复短一点，少追问，涉及钱要冷一点"},
        )
        assert draft.status_code == 404


def test_knowledge_upload_docx_management_and_contact_settings(tmp_path, monkeypatch):
    with build_client(tmp_path, monkeypatch) as client:
        target = client.post(
            "/listen/targets",
            json={"display_name": "A3", "conversation_type": "friend", "local_id": "A3"},
        ).json()["data"]
        conversation_id = target["conversation"]["conversation_id"]
        payload = {
            "filename": "sample.docx",
            "title": "聊天样例",
            "knowledge_type": "默认",
            "tags": ["话术", "回复内容"],
            "content_base64": base64.b64encode(_minimal_docx_bytes()).decode("ascii"),
        }
        uploaded = client.post("/strategy-analysis/documents/upload", json=payload)
        assert uploaded.status_code == 200
        document = uploaded.json()["data"]["document"]
        assert document["source_type"] == "docx"
        assert document["parse_status"] == "success"
        assert document["knowledge_type"] == "默认"

        detail = client.get(f"/strategy-analysis/documents/{document['document_id']}")
        assert detail.status_code == 200
        chunks = detail.json()["data"]["chunks"]
        assert chunks
        assert chunks[0]["source_location"].startswith("docx:paragraph:")

        settings = client.get(f"/strategy-analysis/contacts/{conversation_id}/settings")
        assert settings.status_code == 200
        assert settings.json()["data"]["enabled"] is False

        saved = client.post(
            f"/strategy-analysis/contacts/{conversation_id}/settings",
            json={"enabled": True, "document_ids": [document["document_id"]], "tag_filters": ["话术"]},
        )
        assert saved.status_code == 200
        assert saved.json()["data"]["enabled"] is True
        assert saved.json()["data"]["document_ids"] == [document["document_id"]]

        disabled = client.post(f"/strategy-analysis/documents/{document['document_id']}/disable")
        assert disabled.status_code == 200
        assert disabled.json()["data"]["status"] == "disabled"


def test_rejects_pasted_search_result_or_ui_text(tmp_path, monkeypatch):
    with build_client(tmp_path, monkeypatch) as client:
        polluted = client.post(
            "/strategy-analysis/documents/text",
            json={
                "title": "粘贴的文本",
                "knowledge_type": "默认",
                "tags": ["默认"],
                "content": """
                恋爱攻心术1(1) / 二、态度的选择
                score 0.000
                pdf:page:43
                回复策略、关系判断、回复内容、话术

                联系人知识库开关
                默认关闭
                联系人
                Contact
                启用状态
                Enabled
                """,
            },
        )
        assert polluted.status_code == 400
        assert "疑似把检索结果" in polluted.json()["detail"]


def _minimal_docx_bytes() -> bytes:
    buffer = BytesIO()
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>聊天技巧全集</w:t></w:r></w:p>
        <w:p><w:r><w:t>男：嗨喽！</w:t></w:r></w:p>
        <w:p><w:r><w:t>女：嗨！</w:t></w:r></w:p>
        <w:p><w:r><w:t>回复时先观察对方语气，再自然延伸话题。</w:t></w:r></w:p>
      </w:body>
    </w:document>
    """
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _fake_embed(self, text: str) -> list[float]:
    vector = [0.0] * self.dimensions
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % self.dimensions
        vector[bucket] += 1.0
    if not any(vector):
        vector[0] = 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]
