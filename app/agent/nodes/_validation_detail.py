from __future__ import annotations

import re

_MAX_DETAIL_LENGTH = 500

_KEY_VALUE_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b(\s*[:=]\s*)(?!['\"])[^,\s;]+"),
    re.compile(r"(?i)\b(host|server|port|user|username)\b(\s*[:=]\s*)(?!['\"])[^,\s;]+"),
]

_SECRET_PATTERNS = [
    re.compile(r"(?i)(mysql(?:\+\w+)?|postgresql|postgres|http|https)://[^\s]+"),
    re.compile(r"(?i)\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"(?i)\b[a-z]:\\[^\s]+"),
    re.compile(r"(?i)/(?:users|home|var|etc|tmp|opt)/[^\s]+"),
]

_STACK_PATTERNS = [
    re.compile(r'File "[^"]+", line \d+.*'),
    re.compile(r"Traceback \(most recent call last\):.*", re.DOTALL),
]


def sanitize_validation_detail(exc: Exception) -> str:
    detail = str(exc).replace("\r", " ").replace("\n", " ")
    for pattern in _STACK_PATTERNS:
        detail = pattern.sub("", detail)
    for pattern in _KEY_VALUE_SECRET_PATTERNS:
        detail = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", detail)
    for pattern in _SECRET_PATTERNS:
        detail = pattern.sub("[redacted]", detail)
    detail = re.sub(r"\s+", " ", detail).strip()
    if not detail:
        return "Database rejected SQL"
    return detail[:_MAX_DETAIL_LENGTH]
