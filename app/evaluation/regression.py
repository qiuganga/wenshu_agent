from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegressionResult:
    passed: bool
    regressions: dict[str, float]


class RegressionRunner:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def compare(self, baseline: dict[str, float], current: dict[str, float]) -> RegressionResult:
        regressions: dict[str, float] = {}
        for metric, baseline_value in baseline.items():
            if metric not in current:
                continue
            delta = baseline_value - current[metric]
            if delta > self.threshold:
                regressions[metric] = delta
        return RegressionResult(passed=not regressions, regressions=regressions)
