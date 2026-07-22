import json
import math

import pytest

from app.cache.sanitizer import CachePayloadSanitizer


def test_cache_sanitizer_allowlists_safe_payload_and_removes_sensitive_fields():
    sanitizer = CachePayloadSanitizer()

    payload = sanitizer.sanitize_payload(
        {
            "final_answer": "ok",
            "result_summary": {
                "row_count": 1,
                "password": "secret",
                "input_tokens": 10,
            },
            "sql": "select * from orders",
            "raw_result": [{"password": "secret"}],
            "input_tokens": 10,
        }
    )

    encoded = json.dumps(payload, ensure_ascii=False)
    assert payload["final_answer"] == "ok"
    assert payload["input_tokens"] == 10
    assert "password" not in encoded
    assert "select *" not in encoded
    assert "raw_result" not in encoded


def test_cache_sanitizer_rejects_non_json_values_and_non_finite_numbers():
    sanitizer = CachePayloadSanitizer()

    payload = sanitizer.sanitize_payload({"result_summary": {"value": math.inf, "blob": b"abc"}})

    assert payload == {"result_summary": {}}


def test_cache_sanitizer_rejects_oversize_entry():
    sanitizer = CachePayloadSanitizer(max_entry_bytes=20)

    with pytest.raises(ValueError, match="cache payload exceeds"):
        sanitizer.sanitize_payload({"final_answer": "x" * 100})


def test_cache_sanitizer_handles_cycles():
    value = []
    value.append(value)
    sanitizer = CachePayloadSanitizer()

    payload = sanitizer.sanitize_payload({"result_summary": {"sample": value}})

    assert payload["result_summary"]["sample"] == ["[cycle]"]
