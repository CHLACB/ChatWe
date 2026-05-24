from wx_ai_assistant.domain.enums import MessageType, SenderType
from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.infrastructure.observability.console import print_ai_decision, print_message_snapshot


def test_print_ai_decision_contains_run_id_intent_and_final(capsys):
    print_ai_decision(
        "lg_test",
        "AAxc",
        "你有空吗",
        {
            "intent": "问是否有空",
            "emotion": "neutral",
            "should_reply": True,
            "reply_strategy": "简短确认",
            "safety_action": "allow",
            "final_messages": ["有空，你说"],
        },
    )

    output = capsys.readouterr().out
    assert "[AI DECISION] run_id=lg_test" in output
    assert "intent" in output
    assert "问是否有空" in output
    assert "有空，你说" in output


def test_print_message_snapshot_does_not_print_raw_object_and_truncates(capsys):
    long_text = "很长" * 80
    msg = Message("conv", SenderType.OTHER, MessageType.TEXT, long_text, sender_name="friend")

    print_message_snapshot("AAxc", [msg])

    output = capsys.readouterr().out
    assert "Message(" not in output
    assert "[friend]" in output
    assert "…" in output


def test_print_message_snapshot_lists_items(capsys):
    messages = [
        {"sender_type": "other", "content": "第一句"},
        {"sender_type": "self", "content": "第二句"},
    ]

    print_message_snapshot("AAxc", messages)

    output = capsys.readouterr().out
    assert "1. [friend] 第一句" in output
    assert "2. [self] 第二句" in output
