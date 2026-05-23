from pathlib import Path

from wx_ai_assistant.domain.enums import ConversationType
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
