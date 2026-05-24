from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wx_ai_assistant.domain.models import ConversationIdentity
from wx_ai_assistant.infrastructure.ai.langgraph_agent.models import ContactPolicy


DEFAULT_POLICY = ContactPolicy()


class ContactPolicyLoader:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._loaded = False
        self._default = DEFAULT_POLICY
        self._by_display_name: dict[str, ContactPolicy] = {}
        self._by_remark_name: dict[str, ContactPolicy] = {}
        self._by_local_id: dict[str, ContactPolicy] = {}

    def load_for_identity(self, identity: ConversationIdentity | None, display_name: str = "") -> ContactPolicy:
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
        default_data = data.get("default") if isinstance(data, dict) else None
        if isinstance(default_data, dict):
            self._default = ContactPolicy.model_validate({"name": "default", **default_data})
        contacts = data.get("contacts") if isinstance(data, dict) else None
        if not isinstance(contacts, list):
            return
        for item in contacts:
            if not isinstance(item, dict):
                continue
            policy_data = item.get("policy") if isinstance(item.get("policy"), dict) else {}
            policy = ContactPolicy.model_validate({"name": item.get("name") or item.get("display_name") or "contact", **policy_data})
            self._register(item.get("display_name"), self._by_display_name, policy)
            self._register(item.get("remark_name"), self._by_remark_name, policy)
            self._register(item.get("local_id"), self._by_local_id, policy)

    def _register(self, key: Any, mapping: dict[str, ContactPolicy], policy: ContactPolicy) -> None:
        if isinstance(key, str) and key.strip():
            mapping[key.strip()] = policy
