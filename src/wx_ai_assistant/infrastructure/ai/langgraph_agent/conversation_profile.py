from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wx_ai_assistant.domain.models import ConversationIdentity
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import ConversationProfile


DEFAULT_PROFILE = ConversationProfile()


class ConversationProfileLoader:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._loaded = False
        self._default = DEFAULT_PROFILE
        self._by_display_name: dict[str, ConversationProfile] = {}
        self._by_remark_name: dict[str, ConversationProfile] = {}
        self._by_local_id: dict[str, ConversationProfile] = {}

    def load_for_identity(self, identity: ConversationIdentity | None, display_name: str = "") -> ConversationProfile:
        self._ensure_loaded()
        if identity is not None:
            for key, mapping in [
                (identity.local_id, self._by_local_id),
                (identity.remark_name, self._by_remark_name),
                (identity.display_name, self._by_display_name),
            ]:
                if key and key in mapping:
                    return mapping[key]
        if display_name and display_name in self._by_display_name:
            return self._by_display_name[display_name]
        return self._default

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        default_data = data.get("default")
        if isinstance(default_data, dict):
            self._default = ConversationProfile.model_validate(default_data)

        contacts = data.get("contacts")
        if isinstance(contacts, list):
            for item in contacts:
                self._load_contact_item(item)

        for key, value in data.items():
            if key in {"default", "contacts"} or not isinstance(value, dict):
                continue
            profile = ConversationProfile.model_validate(value)
            self._register(key, self._by_display_name, profile)

    def _load_contact_item(self, item: Any) -> None:
        if not isinstance(item, dict):
            return
        profile_data = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        profile = ConversationProfile.model_validate(profile_data)
        self._register(item.get("display_name"), self._by_display_name, profile)
        self._register(item.get("remark_name"), self._by_remark_name, profile)
        self._register(item.get("local_id"), self._by_local_id, profile)

    def _register(self, key: Any, mapping: dict[str, ConversationProfile], profile: ConversationProfile) -> None:
        if isinstance(key, str) and key.strip():
            mapping[key.strip()] = profile
