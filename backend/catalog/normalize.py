from __future__ import annotations

from typing import Any

from matching.normalizer import fold_whitespace


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not fold_whitespace(value):
        return True
    return False


def as_text(value: Any) -> str | None:
    if is_blank(value):
        return None
    return str(value)


def normalize_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = fold_whitespace(value)
    return collapsed if collapsed else None


def normalize_description(value: str | None) -> str | None:
    return normalize_whitespace(value)
