from __future__ import annotations

import re
from dataclasses import dataclass

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
DATE_RE = re.compile(r"\d{4}[-年/]\d{1,2}(?:[-月/]\d{1,2})?|\d{4}年|\d{1,2}天|\d{1,2}日")
TOP_RE = re.compile(r"(?:top|前|后)\s*(\d+)", re.IGNORECASE)
COMPARE_RE = re.compile(r"(>=|<=|>|<|大于|小于|不少于|不超过|至少|至多)")
DESC_WORDS = ("最高", "最大", "最多", "降序", "top", "前")
ASC_WORDS = ("最低", "最小", "最少", "升序", "后")
NEGATIVE_WORDS = ("不", "非", "排除", "不要", "无")


@dataclass(frozen=True)
class SemanticMatchGuard:
    def allow(self, query: str, candidate_query: str) -> bool:
        return (
            self._numbers(query) == self._numbers(candidate_query)
            and self._dates(query) == self._dates(candidate_query)
            and self._top_n(query) == self._top_n(candidate_query)
            and self._compare(query) == self._compare(candidate_query)
            and self._direction(query) == self._direction(candidate_query)
            and self._negative(query) == self._negative(candidate_query)
        )

    def _numbers(self, text: str) -> tuple[str, ...]:
        return tuple(NUMBER_RE.findall(text))

    def _dates(self, text: str) -> tuple[str, ...]:
        return tuple(DATE_RE.findall(text))

    def _top_n(self, text: str) -> tuple[str, ...]:
        return tuple(TOP_RE.findall(text))

    def _compare(self, text: str) -> tuple[str, ...]:
        return tuple(COMPARE_RE.findall(text))

    def _direction(self, text: str) -> str:
        lowered = text.lower()
        has_desc = any(word in lowered for word in DESC_WORDS)
        has_asc = any(word in lowered for word in ASC_WORDS)
        if has_desc and not has_asc:
            return "desc"
        if has_asc and not has_desc:
            return "asc"
        return "unknown"

    def _negative(self, text: str) -> bool:
        return any(word in text for word in NEGATIVE_WORDS)
