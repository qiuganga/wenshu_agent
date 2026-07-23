from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from typing import Any, cast

WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = WHITESPACE_RE.sub(" ", text)
    return "".join(ch.lower() if "A" <= ch <= "Z" else ch for ch in text)


def normalize_aliases(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_items: Iterable[object] = [value]
    elif isinstance(value, Iterable):
        raw_items = value
    else:
        raw_items = [value]
    normalized = [normalize_text(item) for item in raw_items]
    return tuple(dict.fromkeys(item for item in normalized if item))


def tokenize(value: object) -> tuple[str, ...]:
    text = normalize_text(value)
    tokens = [match.group(0) for match in TOKEN_RE.finditer(text)]
    return tuple(dict.fromkeys(token for token in tokens if token))


def safe_similarity_score(value: object) -> float:
    if value is None:
        return 0.0
    try:
        score = float(cast(Any, value))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score):
        return 0.0
    return max(0.0, min(1.0, score))


def contains_term(text: object, terms: Iterable[str]) -> bool:
    normalized_text = normalize_text(text)
    return any(term and term in normalized_text for term in terms)
