from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SENSITIVE_FIELD_NAMES = frozenset({"password", "passwd", "token", "secret", "api_key", "raw_production_data"})


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    question: str
    expected_sql: str | None = None
    expected_answer: str | None = None
    expected_tables: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    expected_retrieval: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvaluationCase:
        _assert_safe_payload(payload)
        return cls(
            id=str(payload["id"]),
            question=str(payload["question"]),
            expected_sql=_optional_str(payload.get("expected_sql")),
            expected_answer=_optional_str(payload.get("expected_answer")),
            expected_tables=_string_list(payload.get("expected_tables")),
            expected_tools=_string_list(payload.get("expected_tools") or payload.get("expected_tool")),
            expected_retrieval=_string_list(payload.get("expected_retrieval")),
            metadata=dict(payload.get("metadata", {})),
        )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question_hash": _hash_text(self.question),
            "has_expected_sql": self.expected_sql is not None,
            "has_expected_answer": self.expected_answer is not None,
            "expected_tables": list(self.expected_tables),
            "expected_tools": list(self.expected_tools),
            "expected_retrieval": list(self.expected_retrieval),
            "metadata": _safe_metadata(self.metadata),
        }


@dataclass(frozen=True)
class EvaluationDataset:
    version: str
    cases: list[EvaluationCase]
    dataset_hash: str


def load_evaluation_dataset(path: str | Path) -> EvaluationDataset:
    dataset_path = Path(path)
    if dataset_path.suffix.lower() == ".jsonl":
        payloads = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        version = "unknown"
    else:
        raw = json.loads(dataset_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            payloads = raw
            version = "unknown"
        else:
            version = str(raw.get("dataset_version", "unknown"))
            payloads = list(raw.get("cases", []))
    cases = [EvaluationCase.from_dict(payload) for payload in payloads]
    digest_payload = json.dumps([case.to_safe_dict() for case in cases], ensure_ascii=False, sort_keys=True)
    return EvaluationDataset(version=version, cases=cases, dataset_hash=_hash_text(f"{version}:{digest_payload}"))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    return [str(value)]


def _assert_safe_payload(payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in SENSITIVE_FIELD_NAMES:
            raise ValueError(f"evaluation dataset contains forbidden field: {key}")
        if isinstance(value, dict):
            _assert_safe_payload(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _assert_safe_payload(item)


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if str(key).lower() in SENSITIVE_FIELD_NAMES:
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            safe[str(key)] = value
        else:
            safe[str(key)] = str(value)[:200]
    return safe


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
