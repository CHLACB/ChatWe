from wx_ai_assistant.domain.enums import ConversationType
from wx_ai_assistant.domain.models import ConversationIdentity
from wx_ai_assistant.identity.verifier import ConversationVerifier


def test_identity_matches_by_local_id():
    verifier = ConversationVerifier()
    a = ConversationIdentity("conv_a", ConversationType.FRIEND, "张三", local_id="wxid_1")
    b = ConversationIdentity("conv_b", ConversationType.FRIEND, "张三别名", local_id="wxid_1")
    assert verifier.identity_matches(a, b).ok


def test_identity_rejects_wrong_type():
    verifier = ConversationVerifier()
    a = ConversationIdentity("conv_a", ConversationType.FRIEND, "工作群")
    b = ConversationIdentity("conv_b", ConversationType.GROUP, "工作群")
    assert not verifier.identity_matches(a, b).ok
