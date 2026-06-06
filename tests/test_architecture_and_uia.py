from pathlib import Path

from wx_ai_assistant.domain.enums import ConversationType, MessageType, SenderType
from wx_ai_assistant.domain.models import ConversationIdentity
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver
from wx_ai_assistant.ports.wechat_driver import DriverStatus, WindowInfo
from scripts.dump_visible_message_items import dump_visible_message_items


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


def test_search_box_fallback_accepts_unique_header_edit_when_name_changes(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    driver._locators = {
        "search_box": {
            "control_type": "EditControl",
            "name_contains": "搜索",
            "region": "conversation_panel_header",
        }
    }

    class Control:
        def __init__(self, name, control_type, rect, children=None):
            self.Name = name
            self.ControlTypeName = control_type
            self.ClassName = ""
            self.AutomationId = ""
            self.BoundingRectangle = rect
            self._children = children or []

        def GetChildren(self):
            return self._children

    search = Control("AAxc", "EditControl", "Rect(760,250,1015,285)[255x35]")
    driver._window = Control("微信", "WindowControl", "Rect(700,200,2065,1160)[1365x960]", [search])

    assert driver._locate_required("search_box") is search


def test_uia_read_visible_messages_refuses_identity_mismatch(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    expected = ConversationIdentity("conv_a4", ConversationType.FRIEND, "A4")
    actual = ConversationIdentity("conv_a2", ConversationType.FRIEND, "A2")
    driver._ensure_ready = lambda: None  # type: ignore[method-assign]
    driver.get_current_conversation = lambda: actual  # type: ignore[method-assign]
    driver._locate_required = lambda key: object()  # type: ignore[method-assign]

    try:
        driver.read_visible_text_messages(expected)
        assert False, "expected identity mismatch to stop visible-message read"
    except Exception as exc:
        assert "读取消息前会话验证失败" in str(exc)
        assert driver._ingest_identity is None


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


def test_uia_visible_message_type_detects_wechat_media_markers(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")

    assert driver._visible_message_type("[图片]") == MessageType.IMAGE
    assert driver._visible_message_type("[动画表情]") == MessageType.STICKER
    assert driver._visible_message_type("[语音]") == MessageType.VOICE
    assert driver._visible_message_type("这张图片不错") == MessageType.TEXT


def test_uia_capture_visible_media_item_uses_control_capture(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    driver.media_dir = tmp_path / "media"
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    class Item:
        BoundingRectangle = "Rect(100,200,300,360)[200x160]"

        def CaptureToImage(self, path):
            Path(path).write_bytes(b"png")

    media_path = driver._capture_visible_media_item(identity, Item(), SenderType.OTHER, MessageType.STICKER, "abcdef1234567890")

    assert media_path is not None
    assert Path(media_path).exists()
    assert Path(media_path).name.startswith("conv_friend_sticker_abcdef1234567890")


def test_uia_capture_visible_media_item_ignores_text(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    driver.media_dir = tmp_path / "media"
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    class Item:
        BoundingRectangle = "Rect(100,200,300,360)[200x160]"

        def CaptureToImage(self, path):
            raise AssertionError("text messages should not be captured")

    assert driver._capture_visible_media_item(identity, Item(), SenderType.OTHER, MessageType.TEXT, "abcdef") is None


def test_dump_visible_message_items_capture_uses_sender_and_media_fingerprint(tmp_path):
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    class Item:
        Name = "[动画表情]"
        ControlTypeName = "ListItemControl"
        ClassName = ""
        AutomationId = ""
        BoundingRectangle = "Rect(100,100,700,260)[600x160]"

    class FakeDriver:
        def __init__(self):
            self.capture_args = None
            self.fingerprint_message_type = None

        def get_current_conversation(self):
            return identity

        def _locate_required(self, key):
            return object()

        def _message_items(self, message_list):
            return [Item()]

        def _visible_message_content(self, item):
            return item.Name

        def _visible_message_type(self, content):
            return MessageType.STICKER

        def _classify_sender(self, item, current):
            return SenderType.OTHER

        def _media_capture_control(self, item, sender_type, message_type):
            return item

        def _visible_message_fingerprint(self, current, item, sender_type, content, index, message_type=MessageType.TEXT):
            self.fingerprint_message_type = message_type
            return "fingerprint"

        def _capture_visible_media_item(self, current, item, sender_type, message_type, fingerprint):
            self.capture_args = (sender_type, message_type, fingerprint)
            return str(tmp_path / "media.png")

        def _children_count(self, item):
            return 0

        def _iter_controls(self, item, max_depth=3):
            return [item]

    driver = FakeDriver()

    rows = dump_visible_message_items(driver, capture_media=True)

    assert rows[0]["media_path"].endswith("media.png")
    assert rows[0]["detected_sender"] == "other"
    assert driver.fingerprint_message_type == MessageType.STICKER
    assert driver.capture_args == (SenderType.OTHER, MessageType.STICKER, "fingerprint")


def test_uia_media_capture_prefers_bubble_pane_not_avatar(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")

    class RectControl:
        def __init__(self, name, control_type, rect):
            self.Name = name
            self.ControlTypeName = control_type
            self.BoundingRectangle = rect

        def GetChildren(self):
            return []

    class Item:
        BoundingRectangle = "Rect(100,100,700,260)[600x160]"

        def GetChildren(self):
            return [
                RectControl("", "PaneControl", "Rect(100,100,700,260)[600x160]"),
                RectControl("A2", "ButtonControl", "Rect(130,115,181,166)[51x51]"),
                RectControl("", "PaneControl", "Rect(190,100,350,260)[160x160]"),
                RectControl("", "PaneControl", "Rect(350,100,700,260)[350x160]"),
            ]

    control = driver._media_capture_control(Item(), SenderType.OTHER, MessageType.STICKER)

    assert control is not None
    assert str(control.BoundingRectangle).startswith("Rect(190,100,350,260)")


def test_uia_media_fingerprint_is_stable_when_vertical_position_changes(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "A2")

    class ItemA:
        BoundingRectangle = "Rect(190,100,350,260)[160x160]"

    class ItemB:
        BoundingRectangle = "Rect(190,400,350,560)[160x160]"

    first = driver._visible_message_fingerprint(identity, ItemA(), SenderType.OTHER, "[动画表情]", 3, MessageType.STICKER)
    second = driver._visible_message_fingerprint(identity, ItemB(), SenderType.OTHER, "[动画表情]", 8, MessageType.STICKER)

    assert first == second


def test_uia_visible_list_activation_uses_keyboard_not_mouse(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    identity = ConversationIdentity("conv_a2", ConversationType.FRIEND, "A2")

    class Auto:
        def __init__(self):
            self.focused = None
            self.keys = []

        def GetFocusedControl(self):
            return self.focused

        def SendKeys(self, keys):
            self.keys.append(keys)

    class Item:
        Name = "A2"
        ControlTypeName = "ListItemControl"
        BoundingRectangle = "Rect(100,100,300,160)[200x60]"

        def __init__(self):
            self.clicked = False

        def GetChildren(self):
            return []

        def SetFocus(self):
            driver._auto.focused = self

        def Click(self):
            raise AssertionError("visible-list activation must not use mouse click")

    item = Item()
    driver._auto = Auto()
    driver._conversation_list_items = lambda: [item]  # type: ignore[method-assign]

    driver._activate_conversation_from_visible_list(identity)

    assert driver._auto.keys == ["{Enter}"]


def test_uia_conversation_item_signature_detects_passive_left_list_change(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    identity = ConversationIdentity("conv_a2", ConversationType.FRIEND, "A2")

    class Child:
        def __init__(self, name):
            self.Name = name
            self.ControlTypeName = "TextControl"
            self.ClassName = ""

        def GetChildren(self):
            return []

    class Item:
        Name = "A2"
        ControlTypeName = "ListItemControl"
        ClassName = ""

        def __init__(self, preview):
            self.preview = preview

        def GetChildren(self):
            return [Child("A2"), Child(self.preview), Child("15:20")]

    assert driver._conversation_item_changed(identity, Item("旧消息")) is False
    assert driver._conversation_item_changed(identity, Item("旧消息")) is False
    assert driver._conversation_item_changed(identity, Item("新消息")) is True


def test_uia_ingest_identity_cache_is_short_lived(tmp_path):
    driver = UiaWechatDriver(tmp_path / "missing_locators.json")
    identity = ConversationIdentity("conv_friend", ConversationType.FRIEND, "AAxc")

    driver._mark_identity_verified_for_ingest(identity)
    assert driver.get_current_conversation_for_ingest(identity) == identity

    driver._ingest_identity_verified_at -= driver._ingest_identity_ttl_seconds + 1
    assert driver._recent_ingest_identity_matches(identity) is False
