import json
import math
from collections.abc import Iterator, Mapping
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.agent.nodes._result_summary import TRUNCATION_MARKER, summarize_result


class CustomObject:
    def __str__(self):
        return "custom-object at 0xABCDEF"


class BrokenStr:
    def __str__(self):
        raise RuntimeError("boom")


class CustomMapping(Mapping):
    def __init__(self, values: dict[Any, Any]) -> None:
        self._values = values

    def __getitem__(self, key: Any) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def test_summary_empty_result():
    summary = summarize_result([])
    assert summary["row_count"] == 0
    assert summary["columns"] == []
    assert summary["sample"] == []
    assert summary["sample_truncated"] is False


def test_columns_merge_all_rows_stably_and_stringify_keys():
    summary = summarize_result(
        [
            {"region": "east", "amount": 10},
            {"amount": 20, "city": "shanghai"},
            {123: "numeric-key", "region": "north"},
        ]
    )

    assert summary["columns"] == ["region", "amount", "city", "123"]


def test_numeric_stats_support_int_float_decimal_and_skip_none():
    summary = summarize_result(
        [
            {"amount": 10, "rate": 1.5, "decimal_amount": Decimal("2.50")},
            {"amount": 30, "rate": 2.5, "decimal_amount": Decimal("3.50")},
            {"amount": None, "rate": None, "decimal_amount": None},
        ]
    )

    assert summary["numeric_stats"]["amount"]["sum"] == 40
    assert summary["numeric_stats"]["amount"]["avg"] == 20
    assert summary["numeric_stats"]["rate"]["sum"] == 4.0
    assert summary["numeric_stats"]["decimal_amount"]["sum"] == 6.0
    json.dumps(summary, ensure_ascii=False)


def test_bool_values_do_not_participate_in_numeric_stats():
    summary = summarize_result([{"flag": True}, {"flag": False}])

    assert "flag" not in summary["numeric_stats"]


def test_bool_and_int_mixed_counts_only_int_values():
    summary = summarize_result([{"amount": True}, {"amount": 10}, {"amount": False}, {"amount": 30}])

    assert summary["numeric_stats"]["amount"]["count"] == 2
    assert summary["numeric_stats"]["amount"]["sum"] == 40


def test_nan_and_infinity_do_not_enter_numeric_stats():
    summary = summarize_result(
        [
            {"value": math.nan},
            {"value": math.inf},
            {"value": -math.inf},
            {"value": Decimal("NaN")},
            {"value": Decimal("Infinity")},
        ]
    )

    assert "value" not in summary["numeric_stats"]
    json.dumps(summary, ensure_ascii=False)


def test_extreme_decimal_does_not_crash_or_enter_numeric_stats():
    summary = summarize_result([{"value": Decimal("1e1000000")}])

    assert "value" not in summary["numeric_stats"]
    json.dumps(summary, ensure_ascii=False, allow_nan=False)


def test_mixed_decimal_counts_only_json_safe_finite_values():
    summary = summarize_result([{"value": Decimal("2.5")}, {"value": Decimal("1e1000000")}])

    assert summary["numeric_stats"]["value"]["count"] == 1
    assert summary["numeric_stats"]["value"]["sum"] == 2.5
    json.dumps(summary, ensure_ascii=False, allow_nan=False)


def test_sensitive_numeric_field_has_no_stats_and_sample_is_masked():
    summary = summarize_result([{"mobile": 13812345678, "amount": 10}], sample_n=20)

    assert "mobile" not in summary["numeric_stats"]
    assert summary["numeric_stats"]["amount"]["sum"] == 10
    assert summary["sample"] == [{"mobile": "138****5678", "amount": 10}]


def test_truncation_flags_are_split_and_compatible():
    cases = [
        (False, 10, 20, False, False, False),
        (True, 10, 20, True, False, True),
        (False, 30, 20, False, True, True),
        (True, 30, 20, True, True, True),
    ]
    for query_truncated, row_count, sample_n, expected_query, expected_sample, expected_compat in cases:
        summary = summarize_result([{"x": i} for i in range(row_count)], sample_n=sample_n, truncated=query_truncated)
        assert summary["query_result_truncated"] is expected_query
        assert summary["sample_truncated"] is expected_sample
        assert summary["truncated"] is expected_compat


def test_value_truncation_does_not_mark_sample_truncated():
    summary = summarize_result([{"text": "x" * 50}], sample_n=10, sample_value_max_chars=20)

    assert summary["sample"][0]["text"].endswith(TRUNCATION_MARKER)
    assert summary["sample_truncated"] is False


def test_tiny_value_max_chars_never_exceeds_limit():
    for max_chars in [1, 2, 5, len(TRUNCATION_MARKER), len(TRUNCATION_MARKER) + 1]:
        summary = summarize_result([{"text": "x" * 100}], sample_value_max_chars=max_chars)

        value = summary["sample"][0]["text"]
        assert len(value) <= max_chars
        if max_chars <= len(TRUNCATION_MARKER):
            assert value == TRUNCATION_MARKER[:max_chars]
        assert summary["sample_truncated"] is False


def test_non_mapping_rows_are_wrapped_as_value_samples():
    for row in [123, "text", None]:
        summary = summarize_result([row])

        assert summary["columns"] == ["value"]
        assert summary["sample"] == [{"value": row}]
        assert summary["numeric_stats"] == {}
        json.dumps(summary, ensure_ascii=False, allow_nan=False)


def test_mixed_mapping_and_non_mapping_rows_have_consistent_columns_and_samples():
    summary = summarize_result([{"a": 1}, "bad-row", {"b": 2}])

    assert summary["columns"] == ["a", "value", "b"]
    assert summary["sample"] == [{"a": 1}, {"value": "bad-row"}, {"b": 2}]
    assert "value" not in summary["numeric_stats"]
    assert summary["numeric_stats"]["a"]["sum"] == 1
    assert summary["numeric_stats"]["b"]["sum"] == 2
    json.dumps(summary, ensure_ascii=False, allow_nan=False)


def test_custom_mapping_rows_are_supported():
    summary = summarize_result([CustomMapping({"a": 1, "b": 2})])

    assert summary["columns"] == ["a", "b"]
    assert summary["sample"] == [{"a": 1, "b": 2}]
    assert summary["numeric_stats"]["a"]["sum"] == 1


def test_broken_str_value_key_and_set_are_safe():
    broken_key = BrokenStr()
    summary = summarize_result([{broken_key: "key-value", "value": BrokenStr(), "set": {BrokenStr(), "ok"}}])

    sample = summary["sample"][0]
    key = "<unprintable BrokenStr>"
    assert key in summary["columns"]
    assert sample[key] == "key-value"
    assert "<unprintable BrokenStr>" in sample["value"]
    assert any("<unprintable BrokenStr>" in item for item in sample["set"])
    assert "0x" not in json.dumps(summary, ensure_ascii=False, allow_nan=False)


def test_stringified_key_collisions_keep_first_value():
    first_numeric = summarize_result([{1: "a", "1": "b"}])
    first_string = summarize_result([{"1": "a", 1: "b"}])
    multi_row = summarize_result([{"b": 1}, {1: "a", "1": "b"}, {"a": 2}])

    assert first_numeric["columns"] == ["1"]
    assert first_numeric["sample"] == [{"1": "a"}]
    assert first_string["columns"] == ["1"]
    assert first_string["sample"] == [{"1": "a"}]
    assert multi_row["columns"] == ["b", "1", "a"]


def test_cycle_containers_terminate_and_are_json_serializable():
    cycle = []
    cycle.append(cycle)

    summary = summarize_result([{"cycle": cycle}])

    encoded = json.dumps(summary, ensure_ascii=False, allow_nan=False)
    assert "<max-depth-reached>" in encoded


def test_sample_values_are_safe_and_json_serializable():
    summary = summarize_result(
        [
            {
                "long_text": "x" * 100,
                "bytes": b"\xff" * 100,
                "bytearray": bytearray(b"abcdef"),
                "memoryview": memoryview(b"ghijkl"),
                "list": [1, "a", {"nested": "b"}],
                "tuple": (1, 2),
                "set": {"b", "a"},
                "dict": {"z": Decimal("1.20"), 2: [datetime(2026, 7, 19, 1, 2, 3)]},
                "none": None,
                "date": date(2026, 7, 19),
                "datetime": datetime(2026, 7, 19, 1, 2, 3),
                "time": time(1, 2, 3),
                "decimal": Decimal("12.34"),
                "object": CustomObject(),
            }
        ],
        sample_value_max_chars=40,
    )

    sample = summary["sample"][0]
    assert sample["long_text"].endswith(TRUNCATION_MARKER)
    assert sample["bytes"].startswith("<bytes len=100 hex=")
    assert sample["date"] == "2026-07-19"
    assert sample["datetime"] == "2026-07-19T01:02:03"
    assert sample["time"] == "01:02:03"
    assert sample["decimal"] == "12.34"
    assert sample["set"] == ["a", "b"]
    assert "0x" not in sample["object"]
    json.dumps(summary, ensure_ascii=False)
