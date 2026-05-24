from __future__ import annotations

from typing import Any


def sanitize_text(value: str) -> str:
    return value.encode("utf-8", errors="replace").decode("utf-8")


def sanitize_jsonable(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {sanitize_jsonable(key): sanitize_jsonable(item) for key, item in value.items()}
    return value
