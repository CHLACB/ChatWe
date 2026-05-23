from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from wx_ai_assistant.core.exceptions import IdentityVerificationError
from wx_ai_assistant.domain.enums import SenderType
from wx_ai_assistant.domain.models import ConversationIdentity, Message, utc_now
from wx_ai_assistant.ports.wechat_driver import WechatDriver


def normalize_name(value: str | None) -> str:
    return (value or "").strip().lower()


@dataclass
class VerificationResult:
    ok: bool
    reason: str = ""


class ConversationVerifier:
    """Central place for anti-misroute verification.

    Never trust a plain `who` string directly. Use local_id if available; otherwise
    combine type + display/remark name checks. Real projects can enrich this with
    recent-message matching, group member counts, wxid, etc.
    """

    def identity_matches(self, expected: ConversationIdentity, actual: ConversationIdentity | None) -> VerificationResult:
        if actual is None:
            return VerificationResult(False, "无法读取当前会话身份")

        if expected.conversation_type != actual.conversation_type:
            return VerificationResult(False, f"会话类型不一致: expected={expected.conversation_type}, actual={actual.conversation_type}")

        if expected.local_id and actual.local_id:
            if expected.local_id == actual.local_id:
                return VerificationResult(True)
            return VerificationResult(False, f"local_id 不一致: expected={expected.local_id}, actual={actual.local_id}")

        expected_names = {normalize_name(expected.display_name), normalize_name(expected.remark_name)} - {""}
        actual_names = {normalize_name(actual.display_name), normalize_name(actual.remark_name)} - {""}
        if expected_names & actual_names:
            return VerificationResult(True)

        return VerificationResult(False, f"会话名称不匹配: expected={expected_names}, actual={actual_names}")

    def verify_before_ingest(self, expected: ConversationIdentity, current: ConversationIdentity | None) -> None:
        result = self.identity_matches(expected, current)
        if not result.ok:
            raise IdentityVerificationError(f"入库前会话验证失败: {result.reason}")

    def verify_before_send(self, driver: WechatDriver, expected: ConversationIdentity) -> None:
        switch_status = driver.switch_conversation(expected)
        if not switch_status.ok:
            raise IdentityVerificationError(f"切换会话失败: {switch_status.message}")
        current = driver.get_current_conversation()
        result = self.identity_matches(expected, current)
        if not result.ok:
            raise IdentityVerificationError(f"发送前会话验证失败: {result.reason}")

    def verify_after_send(self, driver: WechatDriver, expected: ConversationIdentity, content: str) -> None:
        current = driver.get_current_conversation()
        result = self.identity_matches(expected, current)
        if not result.ok:
            raise IdentityVerificationError(f"发送后会话验证失败: {result.reason}")

        recent = driver.read_visible_text_messages(expected)
        now = utc_now()
        for msg in reversed(recent[-10:]):
            if msg.sender_type == SenderType.SELF and msg.content.strip() == content.strip():
                # The time may be approximate, so do not make this too strict.
                if now - msg.received_at < timedelta(minutes=5):
                    return
        raise IdentityVerificationError("发送后未在最近可见消息中确认到自己刚发送的内容")
