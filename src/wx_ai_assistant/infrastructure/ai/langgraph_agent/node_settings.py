from __future__ import annotations

import json
from pathlib import Path

from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import LangGraphNodeSettings


DEFAULT_NODE_SETTINGS = LangGraphNodeSettings()


class LangGraphNodeSettingsLoader:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._loaded = False
        self._settings = DEFAULT_NODE_SETTINGS

    def load(self) -> LangGraphNodeSettings:
        self._ensure_loaded()
        return self._settings

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            self._settings = LangGraphNodeSettings.model_validate(data)
