from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MetricResult:
    name: str
    score: float
    details: dict[str, Any] = field(default_factory=dict)

    def bounded(self) -> MetricResult:
        return MetricResult(self.name, max(0.0, min(1.0, self.score)), dict(self.details))


def ratio_score(actual: set[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    return len(actual & expected) / len(expected)
