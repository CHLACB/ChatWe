import json

from wx_ai_assistant.infrastructure.ai.prompt_library import compose_system_prompt


def test_compose_system_prompt_uses_core_and_extensions_only(tmp_path):
    core = tmp_path / "core.md"
    turn = tmp_path / "turn.md"
    style = tmp_path / "style.md"
    extensions = tmp_path / "extensions.json"
    core.write_text("最高规则", encoding="utf-8")
    turn.write_text("回合规则", encoding="utf-8")
    style.write_text("短句风格", encoding="utf-8")
    extensions.write_text(
        json.dumps(
            {
                "extensions": [
                    {"name": "关系推进", "enabled": True, "weight": 1.3, "content": "正向时轻微升温"},
                    {"name": "关闭项", "enabled": False, "weight": 2, "content": "不应出现"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    prompt = compose_system_prompt(core, turn, style, "fallback", "off", extensions)

    assert "最高规则" in prompt
    assert "正向时轻微升温" in prompt
    assert "回合规则" not in prompt
    assert "短句风格" not in prompt
    assert "不应出现" not in prompt
    assert "被动回复模式" in prompt
