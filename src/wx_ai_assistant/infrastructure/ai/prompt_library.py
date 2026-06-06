from __future__ import annotations

import json
from pathlib import Path


def load_prompt_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_prompt_extensions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    extensions = data.get("extensions") if isinstance(data, dict) else []
    if not isinstance(extensions, list):
        return []
    normalized: list[dict] = []
    for item in extensions:
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        normalized.append(
            {
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or "未命名扩展").strip(),
                "weight": weight,
                "content": content,
            }
        )
    normalized.sort(key=lambda item: item["weight"], reverse=True)
    return normalized


def compose_extensions_prompt(extensions: list[dict]) -> str:
    parts: list[str] = []
    for item in extensions:
        parts.append(f"[扩展提示词: {item['name']} | 权重 {item['weight']}]\n{item['content']}")
    return "\n\n".join(parts).strip()


def compose_system_prompt(
    core_prompt_path: Path,
    base_prompt_path: Path,
    style_path: Path,
    fallback_prompt: str,
    proactive_mode: str,
    extensions_path: Path | None = None,
) -> str:
    parts: list[str] = []
    core = load_prompt_text(core_prompt_path)
    if core:
        parts.append("[系统提示词]\n" + core)
    elif fallback_prompt:
        parts.append("[系统提示词]\n" + fallback_prompt)
    if extensions_path is not None:
        extensions_prompt = compose_extensions_prompt(load_prompt_extensions(extensions_path))
        if extensions_prompt:
            parts.append("\n[独立扩展提示词]\n" + extensions_prompt)
    parts.append(
        "\n[主动性]\n"
        + (
            "当前允许适度主动追问，但一轮最多输出一次 messages 数组，输出 done=true 后必须停。"
            if proactive_mode == "on"
            else "当前为被动回复模式。只回应对方刚发来的内容；不要自己开启新话题；本轮回复完输出 done=true 后必须停。"
        )
    )
    return "\n".join(parts).strip()
