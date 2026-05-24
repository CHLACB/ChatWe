from pathlib import Path

from wx_ai_assistant.domain.enums import ConversationType, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver
from wx_ai_assistant.ports.wechat_driver import DriverStatus, WindowInfo


def test_api_layer_does_not_import_or_access_driver_directly():
    api_dir = Path(__file__).resolve().parents[1] / "src" / "wx_ai_assistant" / "api"
    for path in api_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "infrastructure.wechat" not in text
        assert "app.state.driver" not in text
        assert ".send_text(" not in text


def test_uia_locator_failure_returns_structured_status(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    driver._auto = object()
    driver._locators = {}
    driver._window = object()
    driver._window_info = WindowInfo(
        hwnd=100,
        title="微信",
        class_name="WeChatMainWndForPC",
        pid=1234,
        visible=True,
        minimized=False,
    )
    driver.restore_and_activate = lambda: DriverStatus(ok=True, mode="uia", message="ok")  # type: ignore[method-assign]

    status = driver.switch_conversation(
        ConversationIdentity("conv_1", ConversationType.FRIEND, "文件传输助手", local_id="filehelper")
    )

    assert not status.ok
    assert status.details["missing_control"] == "switch_conversation"
    assert "dump_commands" in status.details
    assert "不能凭猜测" in status.message


def test_uia_friend_visible_unknown_text_can_be_classified_as_other(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    driver._locators = {
        "message_item": {
            "friend_unknown_text_as_other": True,
            "system_text_patterns": ["撤回了一条消息"],
        }
    }
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    class Item:
        Name = "你好"
        ClassName = ""

        def GetChildren(self):
            return []

    assert driver._classify_sender(Item(), identity) == SenderType.OTHER


def test_uia_friend_visible_system_pattern_stays_system(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    driver._locators = {
        "message_item": {
            "friend_unknown_text_as_other": True,
            "system_text_patterns": ["撤回了一条消息"],
        }
    }
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    class Item:
        Name = "AAxc 撤回了一条消息"
        ClassName = ""

        def GetChildren(self):
            return []

    assert driver._classify_sender(Item(), identity) == SenderType.SYSTEM


def test_uia_group_visible_unknown_text_is_not_friend_fallback(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    driver._locators = {"message_item": {"friend_unknown_text_as_other": True}}
    identity = ConversationIdentity("conv_group", ConversationType.GROUP, "测试群")

    class Item:
        Name = "你好"
        ClassName = ""

        def GetChildren(self):
            return []

    assert driver._classify_sender(Item(), identity) == SenderType.UNKNOWN


def test_uia_visible_fingerprint_does_not_change_when_sender_classification_improves(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    class Item:
        BoundingRectangle = "Rect(100,200,300,260)[200x60]"

    unknown_fp = driver._visible_message_fingerprint(identity, Item(), SenderType.UNKNOWN, "你好", 3)
    other_fp = driver._visible_message_fingerprint(identity, Item(), SenderType.OTHER, "你好", 3)

    assert unknown_fp == other_fp


def test_uia_visible_fingerprint_tolerates_unpaired_surrogate(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    class Item:
        BoundingRectangle = "Rect(100,200,300,260)[200x60]"

    fingerprint = driver._visible_message_fingerprint(identity, Item(), SenderType.OTHER, "bad \ud83d", 3)

    assert fingerprint


def test_uia_ingest_identity_cache_is_short_lived(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    driver._mark_identity_verified_for_ingest(identity)
    assert driver.get_current_conversation_for_ingest(identity) == identity

    driver._ingest_identity_verified_at -= driver._ingest_identity_ttl_seconds + 1
    assert driver._recent_ingest_identity_matches(identity) is False
