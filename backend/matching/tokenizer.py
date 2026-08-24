from __future__ import annotations

import re

from matching.normalizer import SYNONYMS, normalize_text

STOPWORDS = frozenset(
    {
        "W",
        "WITH",
        "AND",
        "THE",
        "A",
        "AN",
        "OF",
        "FOR",
        "TO",
        "X",
    }
)

_TOKEN_RE = re.compile(r"[A-Z0-9]+(?:/[A-Z0-9]+)*")
_SIZE_RE = re.compile(r"^\d+/\d+$")


def tokenize_description(value: str | None) -> list[str]:
    """Split a description into comparison tokens.

    `W/PAULEX` becomes `PAULEX` (stopword `W` dropped). `10/3` stays one token.
    Synonyms such as `LTG` → `LIGHTING` are applied after tokenization.
    """
    normalized = normalize_text(value)
    if not normalized:
        return []
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(normalized):
        parts = [raw] if _SIZE_RE.match(raw) else raw.split("/")
        for part in parts:
            if not part:
                continue
            token = SYNONYMS.get(part, part)
            if token in STOPWORDS:
                continue
            tokens.append(token)
    return tokens
