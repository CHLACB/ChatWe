from pathlib import Path

from wx_ai_assistant.application.app_service import WechatApplicationService
from wx_ai_assistant.application.ai_turn import AiTurnParser
from wx_ai_assistant.application.context_builder import ContextBuilder
from wx_ai_assistant.application.listener_manager import ListenerManager
from wx_ai_assistant.application.media_recognition import MediaRecognitionService
from wx_ai_assistant.application.message_ingestion import MessageIngestionService
from wx_ai_assistant.application.send_queue import SendQueue
from wx_ai_assistant.application.uia_worker import UiaCommandWorker
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus, MessageType, SenderType, SendTaskStatus
from wx_ai_assistant.domain.models import ConversationIdentity, Message
from wx_ai_assistant.identity.verifier import ConversationVerifier
from wx_ai_assistant.infrastructure.ai.dummy_ai import EchoAiGateway
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository
from wx_ai_assistant.infrastructure.wechat.mock_driver import MockWechatDriver
from wx_ai_assistant.ports.history_reader import HistoryResult
from wx_ai_assistant.ports.wechat_driver import DriverStatus, SendResult
from scripts.uia_friend_listener_run import _print_status


class StaticAi:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        self.last_context = ""
        self.last_trigger_content = ""

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        self.calls += 1
        self.last_context = context
        self.last_trigger_content = trigger_message.content
        return self.text


class RaisingAi:
    def __init__(self):
        self.calls = 0

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        self.calls += 1
        raise RuntimeError("ai unavailable")


class InjectDuringAi:
    def __init__(self, driver: MockWechatDriver, identity: ConversationIdentity):
        self.driver = driver
        self.identity = identity
        self.calls = 0

    def generate_reply(self, context: str, trigger_message: Message) -> str:
        self.calls += 1
        if self.calls == 1:
            self.driver.inject_other_text(self.identity, "能不能给我吃吃", "friend")
            self.driver.inject_other_text(self.identity, "我还没吃", "friend")
        return '{"messages":["先回旧消息"],"done":true}'


class FailingHistory:
    def read_history(self, identity: ConversationIdentity, limit: int = 100) -> HistoryResult:
        return HistoryResult(ok=False, messages=[], error="history unavailable")


class FakeVisionGateway:
    def __init__(self):
        self.calls = []

    def describe_image(self, image_path: str, message_type: MessageType, prompt: str = "") -> str:
        self.calls.append((image_path, message_type, prompt))
        return "一张饭菜图片，看起来像面条"


class FakeSpeechGateway:
    def __init__(self):
        self.calls = []

    def transcribe_audio(self, audio_path: str, prompt: str = "") -> str:
        self.calls.append((audio_path, prompt))
        return "我刚刚在路上，晚点回复你"


def build_service(tmp_path: Path, ai=None, auto_send_enabled: bool = True):
    repo = SqliteRepository(tmp_path / "app.sqlite3")
    repo.initialize_schema()
    driver = MockWechatDriver()
    verifier = ConversationVerifier()
    ingestion = MessageIngestionService(repo, driver, verifier)
    context_builder = ContextBuilder(repo, FailingHistory())
    queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message)
    service = WechatApplicationService(
        repo,
        driver,
        ingestion,
        context_builder,
        ai or StaticAi(""),
        queue,
        auto_send_enabled=auto_send_enabled,
    )
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


def other_media(identity: ConversationIdentity, message_type: MessageType, content: str) -> Message:
    return Message(
        conversation_id=identity.conversation_id,
        sender_type=SenderType.OTHER,
        sender_name="friend",
        message_type=message_type,
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
    service.flush_ready_ai_turns(force=True)

    tasks = repo.list_pending_send_tasks()
    assert ai.calls == 1
    assert len(tasks) == 1
    assert tasks[0].content == "reply"


def test_auto_ai_reply_defaults_to_analysis_only_without_send_task(tmp_path):
    ai = StaticAi("reply")
    service, repo, _, _, identity = build_service(tmp_path, ai, auto_send_enabled=False)

    service.handle_realtime_messages(identity, [other_text(identity)])
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
    assert repo.list_pending_send_tasks() == []
    decisions = service.diagnostics_snapshot()["last_ai_turns"]
    assert decisions[0]["parsed_messages"] == ["reply"]
    assert decisions[0]["send_suppressed"] is True
    assert decisions[0]["send_suppressed_reason"] == "auto_send_disabled"


def test_ai_json_messages_are_sent_as_ai_chosen_boundaries(tmp_path):
    ai = StaticAi('{"messages":["先这样","你看可以吗"],"done":true}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    service.handle_realtime_messages(identity, [other_text(identity)])
    service.flush_ready_ai_turns(force=True)

    tasks = repo.list_pending_send_tasks()
    assert ai.calls == 1
    assert [task.content for task in tasks] == ["先这样", "你看可以吗"]


def test_multiple_new_messages_in_one_poll_create_one_ai_turn(tmp_path):
    ai = StaticAi('{"messages":["收到"],"done":true}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    service.handle_realtime_messages(identity, [other_text(identity, "第一句"), other_text(identity, "第二句")])
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
    tasks = repo.list_pending_send_tasks()
    assert len(tasks) == 1
    assert tasks[0].content == "收到"


def test_multiple_user_messages_are_combined_as_one_turn_trigger(tmp_path):
    ai = StaticAi('{"messages":["知道啦"],"done":true}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    service.handle_realtime_messages(
        identity,
        [
            other_text(identity, "吃的啥"),
            other_text(identity, "好吃吗"),
            other_text(identity, "哈哈哈"),
        ],
    )
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
    assert "对方连续发来 3 条消息" in ai.last_trigger_content
    assert "1. 吃的啥" in ai.last_trigger_content
    assert "2. 好吃吗" in ai.last_trigger_content
    assert "3. 哈哈哈" in ai.last_trigger_content
    assert repo.list_pending_send_tasks()[0].trigger_message_id.startswith("turn_")


def test_media_message_is_stored_and_can_trigger_ai(tmp_path):
    ai = StaticAi('{"messages":["看到了"],"done":true}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    service.handle_realtime_messages(identity, [other_media(identity, MessageType.IMAGE, "[图片]")])
    service.flush_ready_ai_turns(force=True)

    stored = repo.list_recent_messages(identity.conversation_id)
    assert stored[-1].message_type == MessageType.IMAGE
    assert stored[-1].media_description == "[图片]"
    assert "[图片识别待补充]" in stored[-1].content
    assert ai.calls == 1
    assert "图片" in ai.last_context
    assert repo.list_pending_send_tasks()[0].content == "看到了"


def test_media_recognition_uses_separate_vision_gateway_when_image_path_exists(tmp_path):
    vision = FakeVisionGateway()
    service = MediaRecognitionService(vision_gateway=vision, enable_vision=True)
    msg = other_media(
        ConversationIdentity("conv", ConversationType.FRIEND, "A2"),
        MessageType.IMAGE,
        "[图片]",
    )
    image = tmp_path / "image.png"
    image.write_bytes(b"fake")
    msg.media_path = str(image)
    msg.media_mime_type = "image/png"

    service.recognize(msg)

    assert vision.calls == [(str(image), MessageType.IMAGE, "")]
    assert msg.media_description == "一张饭菜图片，看起来像面条"
    assert msg.content == "[图片识别] 一张饭菜图片，看起来像面条"


def test_media_recognition_does_not_call_vision_without_image_path(tmp_path):
    vision = FakeVisionGateway()
    service = MediaRecognitionService(vision_gateway=vision, enable_vision=True)
    msg = other_media(
        ConversationIdentity("conv", ConversationType.FRIEND, "A2"),
        MessageType.STICKER,
        "[动画表情]",
    )

    service.recognize(msg)

    assert vision.calls == []
    assert msg.content.startswith("[表情包识别待补充]")


def test_media_recognition_uses_visible_wechat_voice_transcript(tmp_path):
    speech = FakeSpeechGateway()
    service = MediaRecognitionService(speech_gateway=speech, enable_speech=True)
    msg = other_media(
        ConversationIdentity("conv", ConversationType.FRIEND, "A2"),
        MessageType.VOICE,
        "语音转文字：我刚到家",
    )

    service.recognize(msg)

    assert speech.calls == []
    assert msg.media_description == "我刚到家"
    assert msg.content == "[语音转写] 我刚到家"


def test_media_recognition_uses_separate_speech_gateway_when_voice_path_exists(tmp_path):
    speech = FakeSpeechGateway()
    service = MediaRecognitionService(speech_gateway=speech, enable_speech=True)
    msg = other_media(
        ConversationIdentity("conv", ConversationType.FRIEND, "A2"),
        MessageType.VOICE,
        "[语音]",
    )
    audio = tmp_path / "voice.m4a"
    audio.write_bytes(b"fake audio")
    msg.media_path = str(audio)
    msg.media_mime_type = "audio/mp4"

    service.recognize(msg)

    assert speech.calls == [(str(audio), "")]
    assert msg.media_description == "我刚刚在路上，晚点回复你"
    assert msg.content == "[语音转写] 我刚刚在路上，晚点回复你"
    assert msg.media_path == str(audio)
    assert msg.media_mime_type == "audio/mp4"


def test_duplicate_visible_other_media_is_not_inserted_twice(tmp_path):
    ai = StaticAi('{"messages":["看到了"],"done":true}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    first = other_media(identity, MessageType.STICKER, "[动画表情]")
    second = other_media(identity, MessageType.STICKER, "[动画表情]")
    first.fingerprint = "unstable-visible-1"
    second.fingerprint = "unstable-visible-2"

    service.handle_realtime_messages(identity, [first])
    service.flush_ready_ai_turns(force=True)
    service.handle_realtime_messages(identity, [second])
    service.flush_ready_ai_turns(force=True)

    stored = [message for message in repo.list_recent_messages(identity.conversation_id) if message.message_type == MessageType.STICKER]
    assert len(stored) == 1
    assert ai.calls == 1


def test_user_messages_across_quiet_window_are_accumulated_before_ai(tmp_path):
    ai = StaticAi('{"messages":["知道啦"],"done":true}')
    service, _, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)
    service.ai_turn_quiet_seconds = 5.0

    service.handle_realtime_messages(identity, [other_text(identity, "吃的啥")])
    service.handle_realtime_messages(identity, [other_text(identity, "好吃吗")])
    service.handle_realtime_messages(identity, [other_text(identity, "哈哈哈")])
    service.flush_ready_ai_turns()

    assert ai.calls == 0
    pending = service._pending_ai_turns[identity.conversation_id]
    pending.last_other_message_at -= 5.1
    service.flush_ready_ai_turns()

    assert ai.calls == 1
    assert "对方连续发来 3 条消息" in ai.last_trigger_content
    assert "吃的啥" in ai.last_trigger_content
    assert "好吃吗" in ai.last_trigger_content
    assert "哈哈哈" in ai.last_trigger_content


def test_messages_arriving_while_ai_thinks_cancel_stale_reply_and_queue_next_turn(tmp_path):
    service, repo, driver, _, identity = build_service(tmp_path, StaticAi(""))
    ai = InjectDuringAi(driver, identity)
    service.ai = ai
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    first = driver.inject_other_text(identity, "吃的啥", "friend")
    service.handle_realtime_messages(identity, [first])
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
    assert repo.list_pending_send_tasks() == []
    pending = service._pending_ai_turns[identity.conversation_id]
    assert "能不能给我吃吃" in pending.trigger_message.content
    assert "我还没吃" in pending.trigger_message.content


def test_ai_done_false_does_not_send_or_continue(tmp_path):
    ai = StaticAi('{"messages":["还没说完"],"done":false}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    service.handle_realtime_messages(identity, [other_text(identity)])
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
    assert repo.list_pending_send_tasks() == []


def test_ai_turn_waits_for_quiet_window_before_generating(tmp_path):
    ai = StaticAi('{"messages":["收到"],"done":true}')
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)
    service.ai_turn_quiet_seconds = 5.0

    service.handle_realtime_messages(identity, [other_text(identity)])
    service.flush_ready_ai_turns()

    assert ai.calls == 0
    assert repo.list_pending_send_tasks() == []

    pending = service._pending_ai_turns[identity.conversation_id]
    pending.last_other_message_at -= 5.1
    service.flush_ready_ai_turns()

    assert ai.calls == 1
    assert [task.content for task in repo.list_pending_send_tasks()] == ["收到"]


def test_ai_error_is_recorded_without_raising_to_listener(tmp_path):
    ai = RaisingAi()
    service, repo, _, _, identity = build_service(tmp_path, ai)

    service.handle_realtime_messages(identity, [other_text(identity)])
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
    assert repo.list_pending_send_tasks() == []
    assert service._last_ai_errors[-1]["error"] == "ai unavailable"


def test_ingest_uses_driver_ingest_identity_fallback(tmp_path):
    service, repo, driver, _, identity = build_service(tmp_path, StaticAi(""))

    class IngestFallbackDriver(MockWechatDriver):
        def get_current_conversation(self):
            return None

        def get_current_conversation_for_ingest(self, expected):
            return expected

    fallback_driver = IngestFallbackDriver()
    fallback_driver.switch_conversation(identity)
    service.driver = fallback_driver
    service.ingestion.driver = fallback_driver

    service.handle_realtime_messages(identity, [other_text(identity)])

    assert len(repo.list_recent_messages(identity.conversation_id)) == 1


def test_repeated_realtime_fingerprint_does_not_trigger_ai_twice(tmp_path):
    ai = StaticAi("reply")
    service, repo, _, _, identity = build_service(tmp_path, ai)

    first = other_text(identity, "same visible message")
    first.fingerprint = "uia-visible-stable-fingerprint"
    second = other_text(identity, "same visible message")
    second.fingerprint = "uia-visible-stable-fingerprint"

    service.handle_realtime_messages(identity, [first])
    service.flush_ready_ai_turns(force=True)
    service.handle_realtime_messages(identity, [second])
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
    assert len(repo.list_recent_messages(identity.conversation_id)) == 1
    assert len(repo.list_pending_send_tasks()) == 1


def test_old_other_before_visible_self_does_not_trigger_again(tmp_path):
    ai = StaticAi("reply")
    service, repo, _, _, identity = build_service(tmp_path, ai)

    service.handle_realtime_messages(identity, [other_text(identity, "吃饭去了")])
    service.flush_ready_ai_turns(force=True)

    old_other_shifted = other_text(identity, "吃饭去了")
    old_other_shifted.fingerprint = "same-content-new-uia-position"
    service.handle_realtime_messages(identity, [old_other_shifted, self_text(identity, "好，回头聊")])
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
    assert [task.content for task in repo.list_pending_send_tasks()] == ["reply"]


def test_listener_emits_only_visible_delta_when_old_messages_shift(tmp_path):
    ai = StaticAi("reply")
    service, repo, driver, _, identity = build_service(tmp_path, ai)
    repo.set_listen_status(identity.conversation_id, ListenStatus.LISTENING)
    driver.inject_other_text(identity, "旧消息", "friend")
    driver.clear_unread(identity)

    listener = ListenerManager(
        repo,
        driver,
        1,
        service.handle_realtime_messages,
        on_baseline_messages=service.handle_baseline_messages,
        on_after_poll=lambda: service.flush_ready_ai_turns(force=True),
    )
    listener.poll_once()

    driver.inject_other_text(identity, "新消息", "friend")
    listener.poll_once()

    contents = [message.content for message in repo.list_recent_messages(identity.conversation_id)]
    assert contents == ["旧消息", "新消息"]
    assert ai.calls == 1
    assert repo.list_pending_send_tasks()[0].content == "reply"


def test_visible_self_after_send_queue_does_not_duplicate_stored_self_message(tmp_path):
    service, repo, _, _, identity = build_service(tmp_path, StaticAi(""))
    service.ingestion.insert_sent_message(identity, "已经发送")

    visible_self = self_text(identity, "已经发送")
    visible_self.fingerprint = "uia-visible-self-different-position"
    service.handle_realtime_messages(identity, [visible_self])

    messages = repo.list_recent_messages(identity.conversation_id)
    assert len(messages) == 1
    assert messages[0].content == "已经发送"


def test_duplicate_guard_suppresses_same_other_content_with_changed_fingerprint(tmp_path):
    ai = StaticAi("reply")
    service, repo, _, _, identity = build_service(tmp_path, ai)
    service.ai_duplicate_guard_seconds = 120.0

    first = other_text(identity, "同一句")
    first.fingerprint = "first-position"
    second = other_text(identity, "同一句")
    second.fingerprint = "second-position"

    service.handle_realtime_messages(identity, [first])
    service.flush_ready_ai_turns(force=True)
    service.handle_realtime_messages(identity, [second])
    service.flush_ready_ai_turns(force=True)

    assert ai.calls == 1
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
    service.flush_ready_ai_turns(force=True)

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


def test_startup_can_mark_unfinished_send_tasks_failed(tmp_path):
    service, repo, _, _, identity = build_service(tmp_path, StaticAi(""))
    first = service.send_text_manually(identity.conversation_id, "old pending")
    second = service.send_text_manually(identity.conversation_id, "old sending")
    repo.update_send_task(second.send_task_id, SendTaskStatus.SENDING)

    count = repo.fail_unfinished_send_tasks("startup cleanup")

    assert count == 2
    assert repo.get_send_task(first.send_task_id).status == SendTaskStatus.FAILED
    assert repo.get_send_task(second.send_task_id).status == SendTaskStatus.FAILED


def test_failed_send_task_can_be_retried(tmp_path):
    service, repo, _, _, identity = build_service(tmp_path, StaticAi(""))
    task = service.send_text_manually(identity.conversation_id, "retry me")
    repo.update_send_task(task.send_task_id, SendTaskStatus.FAILED, "temporary focus failure")

    retried = service.retry_send_task(task.send_task_id)

    assert retried.status == SendTaskStatus.PENDING
    assert retried.error_message is None
    assert repo.list_pending_send_tasks()[0].send_task_id == task.send_task_id


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
    service.flush_ready_ai_turns(force=True)

    assert len(repo.list_pending_send_tasks()) == 1


def test_single_listener_failure_stops_only_that_target(tmp_path):
    service, repo, _, _, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation

    class OneBadDriver(MockWechatDriver):
        def switch_conversation(self, identity):
            if identity.conversation_id == first.conversation_id:
                return DriverStatus(ok=False, mode="mock", message="boom")
            return super().switch_conversation(identity)

    listener = ListenerManager(repo, OneBadDriver(), 1, lambda identity, messages: None, auto_start_worker=False)
    listener.start_target(first.conversation_id)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    listener.poll_once()

    assert repo.get_listen_target(first.conversation_id).status == ListenStatus.STOPPED
    assert repo.get_listen_target(second.conversation_id).status == ListenStatus.LISTENING


def test_transient_search_box_failure_retries_before_stopping(tmp_path):
    service, repo, _, _, identity = build_service(tmp_path, StaticAi(""))

    class SearchBoxBadDriver(MockWechatDriver):
        def switch_conversation(self, identity):
            return DriverStatus(ok=False, mode="mock", message="未找到 search_box 控件")

    listener = ListenerManager(
        repo,
        SearchBoxBadDriver(),
        1,
        lambda identity, messages: None,
        transient_error_limit=3,
        auto_start_worker=False,
    )
    listener.start_target(identity.conversation_id)
    listener.poll_once()

    target = repo.get_listen_target(identity.conversation_id)
    assert target.status == ListenStatus.LISTENING
    assert "正在重试" in (target.last_error or "")

    listener.poll_once()
    assert repo.get_listen_target(identity.conversation_id).status == ListenStatus.LISTENING

    listener.poll_once()
    assert repo.get_listen_target(identity.conversation_id).status == ListenStatus.STOPPED


def test_listener_baselines_only_one_started_target_per_poll(tmp_path):
    service, repo, driver, _, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation
    listener = ListenerManager(repo, driver, 1, lambda identity, messages: None, auto_start_worker=False)

    listener.start_target(first.conversation_id)
    listener.start_target(second.conversation_id)
    driver.switch_count = 0
    driver.switched_conversation_ids.clear()

    listener.poll_once()

    assert driver.switched_conversation_ids == [first.conversation_id]
    assert repo.get_listen_target(first.conversation_id).status == ListenStatus.LISTENING
    assert repo.get_listen_target(second.conversation_id).status == ListenStatus.LISTENING
    assert repo.get_listen_target(second.conversation_id).last_error is None


def test_listener_identity_mismatch_does_not_stop_target(tmp_path):
    service, repo, _, _, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation

    class MismatchDriver(MockWechatDriver):
        def read_visible_text_messages(self, identity):
            raise RuntimeError(
                f"读取消息前会话验证失败: expected={identity.display_name}, actual={first.display_name}。"
                "已停止读取，避免把当前窗口消息入库到错误联系人。"
            )

    listener = ListenerManager(repo, MismatchDriver(), 1, lambda identity, messages: None, auto_start_worker=False)
    listener.start_target(second.conversation_id)
    listener.poll_once()

    target = repo.get_listen_target(second.conversation_id)
    assert target.status == ListenStatus.LISTENING
    assert "跳过本轮读取" in (target.last_error or "")


def test_listener_first_successful_poll_baselines_visible_messages_without_ai(tmp_path):
    ai = StaticAi("reply")
    service, repo, driver, _, identity = build_service(tmp_path, ai)
    repo.set_listen_status(identity.conversation_id, ListenStatus.LISTENING)
    driver.inject_other_text(identity, "old visible message", "friend")
    driver.clear_unread(identity)

    listener = ListenerManager(
        repo,
        driver,
        1,
        service.handle_realtime_messages,
        on_baseline_messages=service.handle_baseline_messages,
        on_after_poll=lambda: service.flush_ready_ai_turns(force=True),
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


def test_listener_with_two_baselined_targets_no_unread_does_not_switch(tmp_path):
    service, repo, driver, _, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.switch_count = 0
    driver.switched_conversation_ids.clear()

    listener = ListenerManager(repo, driver, 1, lambda identity, messages: None)
    listener._baselined_conversation_ids.update({first.conversation_id, second.conversation_id})
    listener.poll_once()

    assert driver.switch_count == 0
    assert driver.switched_conversation_ids == []


def test_listener_ignores_current_open_target_without_unread(tmp_path):
    ai = StaticAi("reply")
    service, repo, driver, _, first = build_service(tmp_path, ai)
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.switch_conversation(first)
    driver.switch_count = 0
    driver.switched_conversation_ids.clear()
    driver.inject_other_text(first, "当前聊天里的新消息", "friend")
    driver.clear_unread(first)

    listener = ListenerManager(
        repo,
        driver,
        1,
        service.handle_realtime_messages,
        on_after_poll=lambda: service.flush_ready_ai_turns(force=True),
    )
    listener._baselined_conversation_ids.update({first.conversation_id, second.conversation_id})
    listener.poll_once()

    assert driver.switch_count == 0
    assert driver.switched_conversation_ids == []
    assert ai.calls == 0
    assert repo.list_pending_send_tasks() == []


def test_listener_with_two_baselined_targets_only_unread_a_switches_a(tmp_path):
    service, repo, driver, _, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.mark_unread(first)
    driver.switch_count = 0
    driver.switched_conversation_ids.clear()

    listener = ListenerManager(repo, driver, 1, lambda identity, messages: None)
    listener._baselined_conversation_ids.update({first.conversation_id, second.conversation_id})
    listener.poll_once()

    assert driver.switched_conversation_ids == [first.conversation_id]


def test_web_selected_a1_does_not_prevent_a2_unread_processing(tmp_path):
    ai = StaticAi('{"messages":["收到A2"],"done":true}')
    service, repo, driver, _, first = build_service(tmp_path, ai)
    second = service.add_listen_target("A2", ConversationType.FRIEND, local_id="A2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.switch_conversation(first)
    driver.inject_other_text(second, "A2 新消息", "A2")
    driver.switch_count = 0
    driver.switched_conversation_ids.clear()

    listener = ListenerManager(
        repo,
        driver,
        1,
        service.handle_realtime_messages,
        on_after_poll=lambda: service.flush_ready_ai_turns(force=True),
    )
    listener._baselined_conversation_ids.update({first.conversation_id, second.conversation_id})
    listener.poll_once()

    assert driver.switched_conversation_ids == [second.conversation_id]
    assert ai.calls == 1
    assert ai.last_trigger_content == "A2 新消息"
    assert repo.list_pending_send_tasks()[0].conversation_id == second.conversation_id


def test_listener_with_two_baselined_targets_both_unread_processes_one_per_poll(tmp_path):
    service, repo, driver, _, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.mark_unread(first)
    driver.mark_unread(second)
    driver.switch_count = 0
    driver.switched_conversation_ids.clear()

    listener = ListenerManager(repo, driver, 1, lambda identity, messages: None)
    listener._baselined_conversation_ids.update({first.conversation_id, second.conversation_id})
    listener.poll_once()

    assert len(driver.switched_conversation_ids) == 1
    driver.mark_unread(first)
    driver.mark_unread(second)
    listener.poll_once()

    assert set(driver.switched_conversation_ids) == {first.conversation_id, second.conversation_id}
    assert len(driver.switched_conversation_ids) == 2


def test_a2_read_failure_does_not_ingest_a1_messages_as_a2(tmp_path):
    service, repo, driver, _, first = build_service(tmp_path, StaticAi("reply"))
    second = service.add_listen_target("A2", ConversationType.FRIEND, local_id="A2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.switch_conversation(first)
    driver.inject_other_text(first, "A1 的消息", "A1")
    driver.mark_unread(second)

    class StuckOnA1Driver(MockWechatDriver):
        def __init__(self):
            super().__init__()
            self._current = first
            self._messages = driver._messages
            self._unread_conversation_ids = {second.conversation_id}

        def switch_conversation(self, identity):
            self.switch_count += 1
            self.switched_conversation_ids.append(identity.conversation_id)
            return DriverStatus(ok=True, mode="mock", message="pretend switched")

        def read_visible_text_messages(self, identity):
            raise AssertionError("read must not run after target verification fails")

    bad_driver = StuckOnA1Driver()
    listener = ListenerManager(repo, bad_driver, 1, service.handle_realtime_messages)
    listener._baselined_conversation_ids.update({first.conversation_id, second.conversation_id})
    listener.poll_once()

    assert repo.list_recent_messages(second.conversation_id) == []
    target = repo.get_listen_target(second.conversation_id)
    assert target.status == ListenStatus.LISTENING
    assert "跳过本轮读取" in (target.last_error or "")


def test_listener_queues_multiple_unread_targets_and_exposes_snapshot(tmp_path):
    service, repo, driver, _, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("同事", ConversationType.FRIEND, local_id="friend2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.mark_unread(first)
    driver.mark_unread(second)
    driver.switched_conversation_ids.clear()

    listener = ListenerManager(repo, driver, 1, lambda identity, messages: None)
    listener._baselined_conversation_ids.update({first.conversation_id, second.conversation_id})
    listener.poll_once()

    snapshot = listener.snapshot()
    assert len(driver.switched_conversation_ids) == 1
    assert snapshot["last_locked_conversation_id"] in {first.conversation_id, second.conversation_id}
    assert snapshot["last_locked_target"]["conversation_id"] == snapshot["last_locked_conversation_id"]
    assert len(snapshot["pending_active_ids"]) == 1
    assert set(driver.switched_conversation_ids + snapshot["pending_active_ids"]) == {
        first.conversation_id,
        second.conversation_id,
    }


def test_listener_unbaselined_unread_target_triggers_messages_after_divider(tmp_path):
    ai = StaticAi('{"messages":["收到A2"],"done":true}')
    service, repo, driver, _, first = build_service(tmp_path, ai)
    second = service.add_listen_target("A2", ConversationType.FRIEND, local_id="A2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.switch_conversation(first)
    driver.inject_other_text(second, "你好", "A2")
    driver._messages[second.conversation_id].insert(
        0,
        Message(
            conversation_id=second.conversation_id,
            sender_type=SenderType.SYSTEM,
            message_type=MessageType.TEXT,
            content="以下为新消息",
        ),
    )
    driver.switch_count = 0
    driver.switched_conversation_ids.clear()

    listener = ListenerManager(
        repo,
        driver,
        1,
        service.handle_realtime_messages,
        on_baseline_messages=service.handle_baseline_messages,
        on_after_poll=lambda: service.flush_ready_ai_turns(force=True),
    )
    listener._baselined_conversation_ids.add(first.conversation_id)
    listener.poll_once()

    assert driver.switched_conversation_ids == [second.conversation_id]
    assert ai.calls == 1
    assert ai.last_trigger_content == "你好"
    assert repo.list_pending_send_tasks()[0].content == "收到A2"


def test_listener_unbaselined_unread_without_divider_triggers_tail_other_message(tmp_path):
    ai = StaticAi('{"messages":["收到第一条"],"done":true}')
    service, repo, driver, _, first = build_service(tmp_path, ai)
    second = service.add_listen_target("A2", ConversationType.FRIEND, local_id="A2").conversation
    repo.set_listen_status(first.conversation_id, ListenStatus.LISTENING)
    repo.set_listen_status(second.conversation_id, ListenStatus.LISTENING)
    driver.switch_conversation(first)
    driver._messages[second.conversation_id] = [
        Message(
            conversation_id=second.conversation_id,
            sender_type=SenderType.SYSTEM,
            message_type=MessageType.TEXT,
            content="9:37 AM",
        ),
        other_text(second, "你好"),
    ]
    driver.mark_unread(second)
    driver.switched_conversation_ids.clear()

    listener = ListenerManager(
        repo,
        driver,
        1,
        service.handle_realtime_messages,
        on_baseline_messages=service.handle_baseline_messages,
        on_after_poll=lambda: service.flush_ready_ai_turns(force=True),
    )
    listener._baselined_conversation_ids.add(first.conversation_id)
    listener.poll_once()

    stored = repo.list_recent_messages(second.conversation_id)
    assert {message.content for message in stored} == {"9:37 AM", "你好"}
    assert ai.calls == 1
    assert ai.last_trigger_content == "你好"
    assert repo.list_pending_send_tasks()[0].content == "收到第一条"


def test_send_task_switches_to_bound_conversation_before_sending(tmp_path):
    service, repo, driver, queue, first = build_service(tmp_path, StaticAi(""))
    second = service.add_listen_target("A2", ConversationType.FRIEND, local_id="A2").conversation
    driver.switch_conversation(first)
    driver.switch_count = 0
    driver.switched_conversation_ids.clear()

    task = service.send_text_manually(second.conversation_id, "发给 A2")
    queue._process(task)

    assert driver.switched_conversation_ids[0] == second.conversation_id
    assert repo.get_send_task(task.send_task_id).status == SendTaskStatus.SUCCESS
    messages = repo.list_recent_messages(second.conversation_id)
    assert messages[-1].sender_type == SenderType.SELF
    assert messages[-1].content == "发给 A2"


def test_ai_thinking_catch_up_uses_uia_worker_and_keeps_next_turn_pending(tmp_path):
    service, repo, driver, queue, identity = build_service(tmp_path, StaticAi(""))
    uia_worker = UiaCommandWorker(driver, ConversationVerifier())
    service.uia_worker = uia_worker
    queue.uia_worker = uia_worker
    service.ai = InjectDuringAi(driver, identity)
    service.ai_turn_parser = AiTurnParser(max_messages=3, strict_json=True)

    first = driver.inject_other_text(identity, "吃的啥", "friend")
    service.handle_realtime_messages(identity, [first])
    service.flush_ready_ai_turns(force=True)

    assert repo.list_pending_send_tasks() == []
    pending = service._pending_ai_turns[identity.conversation_id]
    assert "能不能给我吃吃" in pending.trigger_message.content
    assert "我还没吃" in pending.trigger_message.content
    assert uia_worker.snapshot()["recent_tasks"][-1]["kind"] == "read_target_messages"


def test_mock_mode_main_chain_runs_through_queue_and_stores_self_message(tmp_path):
    service, repo, driver, queue, identity = build_service(tmp_path, EchoAiGateway())

    service.create_mock_text_message(identity.conversation_id, "你好", "friend")
    service.flush_ready_ai_turns(force=True)
    task = repo.list_pending_send_tasks()[0]
    queue._process(task)

    messages = repo.list_recent_messages(identity.conversation_id)
    assert [m.sender_type for m in messages] == [SenderType.OTHER, SenderType.SELF]
    assert messages[-1].content == "收到：你好"


def test_debug_turns_output_contains_run_id_and_intent(tmp_path, capsys):
    service, repo, driver, _, _ = build_service(tmp_path, StaticAi(""))
    service._last_ai_turns.append(
        {
            "run_id": "lg_test",
            "display_name": "AAxc",
            "trigger_content": "你有空吗",
            "intent": "问是否有空",
            "emotion": "中性",
            "should_reply": True,
            "reply_strategy": "简短确认",
            "draft_messages": ["有空"],
            "safety_action": "allow",
            "safety_reasons": [],
            "final_messages": ["有空"],
            "parsed_messages": ["有空"],
            "raw_reply": '{"messages":["有空"],"done":true}',
            "context_tail": "ctx",
        }
    )

    _print_status(repo, driver, service, debug_turns=True)

    output = capsys.readouterr().out
    assert "[AI DECISION] run_id=lg_test" in output
    assert "问是否有空" in output
