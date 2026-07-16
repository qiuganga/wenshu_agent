from __future__ import annotations

import re

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_IDENTIFIER_LENGTH = 64
MAX_IDENTIFIER_LIMIT = 100_000


class IdentifierError(ValueError):
    pass


def validate_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise IdentifierError("identifier must be a string")
    if not value or len(value) > MAX_IDENTIFIER_LENGTH:
        raise IdentifierError("identifier length is invalid")
    if not IDENTIFIER_RE.fullmatch(value):
        raise IdentifierError("identifier contains unsafe characters")
    return value


def quote_mysql_identifier(value: str) -> str:
    return f"`{validate_identifier(value)}`"


def quote_mysql_qualified_identifier(value: str) -> str:
    parts = value.split(".")
    if not 1 <= len(parts) <= 2:
        raise IdentifierError("qualified identifier must be table or schema.table")
    return ".".join(quote_mysql_identifier(part) for part in parts)


def safe_limit(value: int, max_limit: int = MAX_IDENTIFIER_LIMIT) -> int:
    if not isinstance(value, int):
        raise IdentifierError("limit must be an integer")
    if value < 0:
        raise IdentifierError("limit must not be negative")
    return min(value, max_limit)
