from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from app.security.data_masking import is_sensitive_field

SAFE_PAYLOAD_KEYS = {
    "cache_hit",
    "cache_type",
    "data_version",
    "estimated_cost",
    "execution_time_ms",
    "final_answer",
    "fallback_used",
    "input_tokens",
    "model_name",
    "normalized_query_summary",
    "output_tokens",
    "prompt_hash",
    "prompt_name",
    "prompt_version",
    "query_result_truncated",
    "result_summary",
    "row_count",
    "sample_truncated",
    "sql_hash",
    "table_ids",
    "token_usage",
    "total_tokens",
    "truncated",
}
SENSITIVE_EXACT_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "connection_string",
    "cookie",
    "dsn",
    "full_sql",
    "messages",
    "password",
    "passwd",
    "prompt",
    "query_result",
    "raw_result",
    "refresh_token",
    "response",
    "secret",
    "sql",
    "token",
    "traceback",
}


class CachePayloadSanitizer:
    def __init__(
        self,
        *,
        max_depth: int = 5,
        max_items: int = 50,
        max_string_chars: int = 500,
        max_entry_bytes: int = 65536,
    ) -> None:
        self.max_depth = max_depth
        self.max_items = max_items
        self.max_string_chars = max_string_chars
        self.max_entry_bytes = max_entry_bytes

    def sanitize_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            text_key = str(key)
            if text_key not in SAFE_PAYLOAD_KEYS:
                continue
            safe_value = self._sanitize_value(text_key, value, depth=0, seen=set())
            if safe_value is not None:
                sanitized[text_key] = safe_value
        encoded = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > self.max_entry_bytes:
            raise ValueError("cache payload exceeds max_entry_bytes")
        return sanitized

    def _sanitize_value(self, key: str, value: Any, *, depth: int, seen: set[int]) -> Any | None:
        normalized_key = key.lower()
        if normalized_key in SENSITIVE_EXACT_KEYS or is_sensitive_field(normalized_key):
            return None
        if depth > self.max_depth:
            return "[truncated]"
        if value is None or isinstance(value, bool | str | int):
            return self._sanitize_scalar(value)
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, bytes | bytearray | memoryview):
            return None
        if isinstance(value, Mapping):
            marker = id(value)
            if marker in seen:
                return "[cycle]"
            seen.add(marker)
            output: dict[str, Any] = {}
            for nested_key, nested_value in list(value.items())[: self.max_items]:
                text_key = str(nested_key)[: self.max_string_chars]
                if text_key.lower() in SENSITIVE_EXACT_KEYS or is_sensitive_field(text_key):
                    continue
                safe = self._sanitize_value(text_key, nested_value, depth=depth + 1, seen=seen)
                if safe is not None and text_key not in output:
                    output[text_key] = safe
            seen.remove(marker)
            return output
        if isinstance(value, list | tuple):
            marker = id(value)
            if marker in seen:
                return "[cycle]"
            seen.add(marker)
            values = [
                safe
                for item in list(value)[: self.max_items]
                if (safe := self._sanitize_value(key, item, depth=depth + 1, seen=seen)) is not None
            ]
            seen.remove(marker)
            return values
        return None

    def _sanitize_scalar(self, value: Any) -> Any:
        if isinstance(value, str):
            return value[: self.max_string_chars]
        return value


def payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
