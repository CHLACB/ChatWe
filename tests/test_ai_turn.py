from wx_ai_assistant.application.ai_turn import AiTurnParser


def test_ai_turn_parser_keeps_model_chosen_message_boundaries():
    turn = AiTurnParser(max_messages=3, strict_json=True).parse('{"messages":["一句","另一句"],"done":true}')

    assert turn.done is True
    assert turn.messages == ["一句", "另一句"]


def test_ai_turn_parser_does_not_split_plain_text():
    text = "第一句。第二句。第三句。"
    turn = AiTurnParser(max_messages=3, strict_json=False).parse(text)

    assert turn.messages == [text]


def test_ai_turn_parser_strict_json_rejects_plain_text():
    turn = AiTurnParser(max_messages=3, strict_json=True).parse("一大段普通文本")

    assert turn.done is False
    assert turn.messages == []


def test_ai_turn_parser_sanitizes_unpaired_surrogates():
    turn = AiTurnParser(max_messages=3, strict_json=False).parse("收到：\ud83d")

    assert turn.messages == ["收到：?"]
