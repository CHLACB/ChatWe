from wx_ai_assistant.infrastructure.ai.prompt_library import compose_system_prompt


def test_compose_system_prompt_includes_core_before_turn_and_style(tmp_path):
    core = tmp_path / "core.md"
    turn = tmp_path / "turn.md"
    style = tmp_path / "style.md"
    core.write_text("最高规则", encoding="utf-8")
    turn.write_text("回合规则", encoding="utf-8")
    style.write_text("短句风格", encoding="utf-8")

    prompt = compose_system_prompt(core, turn, style, "fallback", "off")

    assert prompt.index("最高规则") < prompt.index("回合规则") < prompt.index("短句风格")
    assert "被动回复模式" in prompt
