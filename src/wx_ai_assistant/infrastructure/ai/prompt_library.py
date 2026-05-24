from __future__ import annotations

from pathlib import Path


def load_prompt_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def compose_system_prompt(base_prompt_path: Path, style_path: Path, fallback_prompt: str, proactive_mode: str) -> str:
    parts: list[str] = []
    base = load_prompt_text(base_prompt_path)
    style = load_prompt_text(style_path)
    parts.append(base or fallback_prompt)
    if style:
        parts.append("\n[风格库]\n" + style)
    parts.append(
        "\n[主动性]\n"
        + (
            "当前允许适度主动追问，但一轮最多输出一次 messages 数组，输出 done=true 后必须停。"
            if proactive_mode == "on"
            else "当前为被动回复模式。只回应对方刚发来的内容；不要自己开启新话题；本轮回复完输出 done=true 后必须停。"
        )
    )
    return "\n".join(parts).strip()
