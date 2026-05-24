from pathlib import Path

from wx_ai_assistant.application.app_service import WechatApplicationService
from wx_ai_assistant.application.ai_turn import AiTurnParser
from wx_ai_assistant.application.context_builder import ContextBuilder
from wx_ai_assistant.application.listener_manager import ListenerManager
from wx_ai_assistant.application.message_ingestion import MessageIngestionService
from wx_ai_assistant.application.send_queue import SendQueue
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus, MessageType, SenderType, SendTaskStatus
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.identity.verifier import ConversationVerifier
from wx_ai_assistant.infrastructure.ai.dummy_ai import EchoAiGateway
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository
from wx_ai_assistant.infrastructure.wechat.mock_driver import MockWechatDriver
from wx_ai_assistant.ports.history_reader import HistoryResult
from wx_ai_assistant.ports.wechat_driver import DriverStatus, SendResult


class StaticAi:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        self.calls += 1
        return self.text


class FailingHistory:
    def read_history(self, identity: ConversationIdentity, limit: int = 100) -> HistoryResult:
        return HistoryResult(ok=False, messages=[], error="history unavailable")


def build_service(tmp_path: Path, ai=None):
    repo = SqliteRepository(tmp_path / "app.sqlite3")
    repo.initialize_schema()
    driver = MockWechatDriver()
    verifier = ConversationVerifier()
    ingestion = MessageIngestionService(repo, driver, verifier)
    context_builder = ContextBuilder(repo, FailingHistory())
    queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message)
    service = WechatApplicationService(repo, driver, ingestion, context_builder, ai or StaticAi(""), queue)
    identity = service.add_listen_target("文件传输助手", ConversationType.FRIEND, local_id="filehelper").conversation
    driver.switch_conversation(identity)
    return service, repo, driver, queue, identity


def other_text(identity: ConversationIdentity, content: str = "hello") -> Message:
    return Message(
        conversation_id=identity.conversation_id,
        sender_type=SenderType.OTHER,
        sender_name="friend",
        message_type=MessageType.TEXT,
        content=content,
    )


def self_text(identity: ConversationIdentity, content: str = "me") -> Message:
    return Message(
        conversation_id=identity.conversation_id,
        sender_type=SenderType.SELF,
        sender_name="self",
        message_type=MessageType.TEXT,
        content=content,
    )


def test_self_message_is_stored_but_does_not_trigger_ai(tmp_path):
    ai = StaticAi("reply")
    service, repo, _, _, identity = build_service(tmp_path, ai)

    service.handle_realtime_messages(identity, [self_text(identity)])

    assert ai.calls == 0
    assert len(repo.list_recent_messages(identity.conversation_id)) == 1
    assert repo.list_pending_send_tasks() == []


def test_other_message_triggers_ai_and_nonempty_reply_creates_send_task(tmp_path):
    ai = StaticAi("reply")
    service, repo, _, _, identity = build_service(tmp_path, ai)

    service.handle_realtime_messages(identity, [other_text(identity)])

    tasks = repo.list_pending_send_tasks()
    assert ai.calls == 1
    assert len(tasks) == 1
    assert tasks[0].content == "reply"


def test_ai_json_messages_are_sent_as_ai_chosen_boundaries(tmp_path):
    ai = StaticAi('{"messages":["先这样","你看可以吗"],"done":true}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    service.handle_realtime_messages(identity, [other_text(identity)])

    tasks = repo.list_pending_send_tasks()
    assert ai.calls == 1
    assert [task.content for task in tasks] == ["先这样", "你看可以吗"]


def test_multiple_new_messages_in_one_poll_create_one_ai_turn(tmp_path):
    ai = StaticAi('{"messages":["收到"],"done":true}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    service.handle_realtime_messages(identity, [other_text(identity, "第一句"), other_text(identity, "第二句")])

    assert ai.calls == 1
    tasks = repo.list_pending_send_tasks()
    assert len(tasks) == 1
    assert tasks[0].content == "收到"


def test_ai_done_false_does_not_send_or_continue(tmp_path):
    ai = StaticAi('{"messages":["还没说完"],"done":false}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    service.handle_realtime_messages(identity, [other_text(identity)])

    assert ai.calls == 1
    assert repo.list_pending_send_tasks() == []


def test_repeated_realtime_fingerprint_does_not_trigger_ai_twice(tmp_path):
    ai = StaticAi("reply")
    service, repo, _, _, identity = build_service(tmp_path, ai)

    first = other_text(identity, "same visible message")
    first.fingerprint = "uia-visible-stable-fingerprint"
    second = other_text(identity, "same visible message")
    second.fingerprint = "uia-visible-stable-fingerprint"

    service.handle_realtime_messages(identity, [first])
    service.handle_realtime_messages(identity, [second])

    assert ai.calls == 1
    assert len(repo.list_recent_messages(identity.conversation_id)) == 1
    assert len(repo.list_pending_send_tasks()) == 1


def test_unlisted_conversation_is_not_processed(tmp_path):
    service, repo, driver, _, _ = build_service(tmp_path, StaticAi("reply"))
    unknown = ConversationIdentity("conv_unknown", ConversationType.FRIEND, "陌生人")
    driver.switch_conversation(unknown)

    service.handle_realtime_messages(unknown, [other_text(unknown)])

    assert repo.list_recent_messages(unknown.conversation_id) == []
    assert repo.list_pending_send_tasks() == []


def test_group_listen_target_is_rejected_in_first_phase(tmp_path):
    service, _, _, _, _ = build_service(tmp_path, StaticAi(""))

    try:
        service.add_listen_target("测试群", ConversationType.GROUP, local_id="group1")
    except ValueError as exc:
        assert "只支持好友私聊" in str(exc)
    else:
        raise AssertionError("group listen target should be rejected")


def test_empty_ai_reply_does_not_create_send_task(tmp_path):
    service, repo, _, _, identity = build_service(tmp_path, StaticAi("  "))

    service.handle_realtime_messages(identity, [other_text(identity)])

    assert repo.list_pending_send_tasks() == []


def test_send_queue_verifies_before_send_and_does_not_send_on_mismatch(tmp_path):
    service, repo, _, queue, identity = build_service(tmp_path, StaticAi(""))
    task = service.send_text_manually(identity.conversation_id, "reply")

    class BadBeforeDriver(MockWechatDriver):
        def switch_conversation(self, identity):
            return DriverStatus(ok=True, mode="mock", message="pretend switched")

        def get_current_conversation(self):
            return ConversationIdentity("other", ConversationType.FRIEND, "其他人")

        def send_text(self, identity, content):
            raise AssertionError("send_text should not be called")

    queue.driver = BadBeforeDriver()
    queue._process(task)

    assert repo.list_pending_send_tasks() == []
    row = repo._conn.execute("SELECT status FROM send_tasks WHERE send_task_id=?", (task.send_task_id,)).fetchone()
    assert row["status"] == SendTaskStatus.FAILED.value


def test_manual_send_rejects_unknown_conversation(tmp_path):
    service, _, _, _, _ = build_service(tmp_path, StaticAi(""))

    try:
        service.send_text_manually("missing", "hello")
    except ValueError as exc:
        assert "会话不存在" in str(exc)
    else:
        raise AssertionError("manual send to unknown conversation should be rejected")


def test_send_task_query_returns_tasks_by_status(tmp_path):
    service, repo, _, _, identity = build_service(tmp_path, StaticAi(""))

    task = service.send_text_manually(identity.conversation_id, "queued")

    all_tasks = service.list_send_tasks()
    pending_tasks = service.list_send_tasks(status=SendTaskStatus.PENDING)
    one = service.get_send_task(task.send_task_id)

    assert [t.send_task_id for t in all_tasks] == [task.send_task_id]
    assert [t.send_task_id for t in pending_tasks] == [task.send_task_id]
    assert one and one.content == "queued"
    assert repo.get_send_task("missing") is None


def test_send_queue_marks_failed_when_after_send_verification_fails(tmp_path):
    service, repo, _, queue, identity = build_service(tmp_path, StaticAi(""))
    task = service.send_text_manually(identity.conversation_id, "reply")

    class BadAfterDriver(MockWechatDriver):
        def send_text(self, identity, content):
            return SendResult(ok=True, message="sent without visible self message")

    driver = BadAfterDriver()
    driver.switch_conversation(identity)
    queue.driver = driver
    queue._process(task)

    row = repo._conn.execute("SELECT status FROM send_tasks WHERE send_task_id=?", (task.send_task_id,)).fetchone()
    assert row["status"] == SendTaskStatus.FAILED.value


def test_history_failure_does_not_block_realtime_ai_flow(tmp_path):
    service, repo, _, _, identity = build_service(tmp_path, StaticAi("reply"))

    service.handle_realtime_messages(identity, [other_text(identity)])

    assert len(repo.list_pending_send_tasks()) == 1


def test_single_listener_failure_stops_only_that_target(tmp_path):
    service, repo, _, _, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)

    class OneBadDriver(MockWechatDriver):
        def switch_conversation(self, identity):
            if identity.conversation_id == first.conversation_id:
                return DriverStatus(ok=False, mode="mock", message="boom")
            return super().switch_conversation(identity)

    listener = ListenerManager(repo, OneBadDriver(), 1, lambda identity, messages: None)
    listener.poll_once()

    assert repo.get_listen_target(first.conversation_id).status == ListenStatus.STOPPED
    assert repo.get_listen_target(second.conversation_id).status == ListenStatus.LISTENING


def test_listener_first_successful_poll_baselines_visible_messages_without_ai(tmp_path):
    ai = StaticAi("reply")
    service, repo, driver, _, identity = build_service(tmp_path, ai)
    repo.set_listen_status(identity.conversation_id, ListenStatus.LISTENING)
    driver.inject_other_text(identity, "old visible message", "friend")

    listener = ListenerManager(
        repo,
        driver,
        1,
        service.handle_realtime_messages,
        on_baseline_messages=service.handle_baseline_messages,
    )
    listener.poll_once()

    assert ai.calls == 0
    assert len(repo.list_recent_messages(identity.conversation_id)) == 1
    assert repo.list_pending_send_tasks() == []

    driver.inject_other_text(identity, "new visible message", "friend")
    listener.poll_once()

    assert ai.calls == 1
    tasks = repo.list_pending_send_tasks()
    assert len(tasks) == 1
    assert tasks[0].content == "reply"


def test_mock_mode_main_chain_runs_through_queue_and_stores_self_message(tmp_path):
    service, repo, driver, queue, identity = build_service(tmp_path, EchoAiGateway())

    service.create_mock_text_message(identity.conversation_id, "你好", "friend")
    task = repo.list_pending_send_tasks()[0]
    queue._process(task)

    messages = repo.list_recent_messages(identity.conversation_id)
    assert [m.sender_type for m in messages] == [SenderType.OTHER, SenderType.SELF]
    assert messages[-1].content == "收到：你好"
