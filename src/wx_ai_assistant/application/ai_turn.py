from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AiTurn:
    messages: list[str]
    done: bool = True


class AiTurnParser:
    """Parse AI-chosen WeChat message boundaries.

    The parser does not split paragraphs by punctuation. In JSON mode, message
    boundaries come from the model's `messages` array. Plain text is kept as one
    message only for backward-compatible mock/echo tests.
    """

    def __init__(self, max_messages: int = 3, strict_json: bool = False):
        self.max_messages = max(1, max_messages)
        self.strict_json = strict_json

    def parse(self, raw: str) -> AiTurn:
        text = raw.strip()
        if not text:
            return AiTurn(messages=[], done=True)
        data = self._try_load_json(text)
        if isinstance(data, dict):
            done = bool(data.get("done", True))
            messages = data.get("messages", [])
            if isinstance(messages, str):
                messages = [messages]
            if not isinstance(messages, list):
                messages = []
            normalized = [str(item).strip() for item in messages if str(item).strip()]
            if not done:
                return AiTurn(messages=[], done=False)
            return AiTurn(messages=normalized[: self.max_messages], done=True)
        if self.strict_json:
            return AiTurn(messages=[], done=False)
        return AiTurn(messages=[text], done=True)

    def _try_load_json(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                fenced = "\n".join(lines[1:-1]).strip()
                try:
                    return json.loads(fenced)
                except json.JSONDecodeError:
                    return None
        return None
