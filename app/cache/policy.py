from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.cache.models import CacheWriteDecision
from app.cache.sanitizer import SENSITIVE_EXACT_KEYS
from app.security.data_masking import is_sensitive_field


class CachePolicy:
    def __init__(self, *, max_entry_bytes: int, cache_safe_final_summary: bool = False) -> None:
        self.max_entry_bytes = max_entry_bytes
        self.cache_safe_final_summary = cache_safe_final_summary

    def can_write(
        self, *, final_status: str, payload: Mapping[str, Any], metadata: Mapping[str, Any]
    ) -> CacheWriteDecision:
        if final_status != "success":
            return CacheWriteDecision(False, "final_status_not_success")
        if metadata.get("read_only") is False:
            return CacheWriteDecision(False, "not_read_only")
        if metadata.get("fallback_used") is True:
            return CacheWriteDecision(False, "llm_fallback_used")
        if metadata.get("checkpoint_resumed") is True:
            return CacheWriteDecision(False, "checkpoint_resumed")
        if metadata.get("execution_outcome_unknown") is True:
            return CacheWriteDecision(False, "execution_unknown")
        if not metadata.get("data_version"):
            return CacheWriteDecision(False, "missing_data_version")
        if self._has_sensitive_keys(payload):
            return CacheWriteDecision(False, "sensitive_payload")
        if not self.cache_safe_final_summary and "final_answer" in payload:
            return CacheWriteDecision(False, "final_answer_cache_disabled")
        try:
            size = len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
        except Exception:
            return CacheWriteDecision(False, "payload_not_json")
        if size > self.max_entry_bytes:
            return CacheWriteDecision(False, "payload_too_large")
        return CacheWriteDecision(True)

    def _has_sensitive_keys(self, value: Any) -> bool:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                text_key = str(key).lower()
                if text_key in SENSITIVE_EXACT_KEYS or is_sensitive_field(text_key):
                    return True
                if self._has_sensitive_keys(nested):
                    return True
        if isinstance(value, list | tuple):
            return any(self._has_sensitive_keys(item) for item in value)
        return False
