from __future__ import annotations

from collections.abc import Iterable
from typing import Any

DEFAULT_SENSITIVE_FIELDS = frozenset(
    {
        "phone",
        "mobile",
        "telephone",
        "id_card",
        "identity_card",
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "email",
        "bank_card",
        "account_no",
    }
)


def _normalized_fields(fields: Iterable[str] | None) -> set[str]:
    return {field.lower() for field in (fields or DEFAULT_SENSITIVE_FIELDS)}


def is_sensitive_field(field_name: str, sensitive_fields: Iterable[str] | None = None) -> bool:
    lowered = field_name.lower()
    return lowered in _normalized_fields(sensitive_fields)


def mask_value(field_name: str, value: Any, sensitive_fields: Iterable[str] | None = None) -> Any:
    if value is None or not is_sensitive_field(field_name, sensitive_fields):
        return value

    lowered = field_name.lower()
    text = str(value)
    if lowered in {"password", "passwd", "secret", "token", "api_key"}:
        return "***"
    if lowered in {"phone", "mobile", "telephone"}:
        return f"{text[:3]}****{text[-4:]}" if len(text) >= 7 else "***"
    if lowered in {"id_card", "identity_card"}:
        return f"{text[:3]}********{text[-4:]}" if len(text) >= 7 else "***"
    if lowered == "email":
        if "@" not in text:
            return "***"
        name, domain = text.split("@", 1)
        prefix = name[:2] if len(name) > 1 else name[:1]
        return f"{prefix}***@{domain}"
    if lowered in {"bank_card", "account_no"}:
        return f"****{text[-4:]}" if len(text) >= 4 else "***"
    return "***"


def mask_row(row: dict[str, Any], sensitive_fields: Iterable[str] | None = None) -> dict[str, Any]:
    return {key: mask_value(key, value, sensitive_fields) for key, value in row.items()}


def mask_rows(rows: list[dict[str, Any]], sensitive_fields: Iterable[str] | None = None) -> list[dict[str, Any]]:
    return [mask_row(row, sensitive_fields) for row in rows]
