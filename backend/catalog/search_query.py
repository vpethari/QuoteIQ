from __future__ import annotations

from matching.noise import strip_quantity_and_noise
from matching.tokenizer import tokenize_description


def retrieval_search_string(query: str) -> str:
    """Lowercased retrieval string. Python still owns synonym/unit/noise handling."""
    cleaned = strip_quantity_and_noise(query)
    tokens = [token.lower() for token in tokenize_description(cleaned) if token]
    if tokens:
        return " ".join(tokens)
    return cleaned.lower().strip()


def retrieval_search_tokens(query: str, *, limit: int = 8) -> list[str]:
    cleaned = strip_quantity_and_noise(query)
    tokens = tokenize_description(cleaned)
    distinctive = [
        token.lower()
        for token in tokens
        if token.replace(".", "", 1).isdigit() or len(token) >= 3
    ]
    if not distinctive:
        distinctive = [token.lower() for token in tokens if token]
    return distinctive[:limit]
