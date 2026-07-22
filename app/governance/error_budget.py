from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorBudgetSnapshot:
    status: str
    remaining_ratio: float
    observed_system_errors: int
    allowed_errors: int


class ErrorBudgetManager:
    def __init__(self, *, warning_ratio: float, exhausted_ratio: float, recovery_ratio: float) -> None:
        self.warning_ratio = warning_ratio
        self.exhausted_ratio = exhausted_ratio
        self.recovery_ratio = recovery_ratio
        self._last_status = "HEALTHY"

    def evaluate(self, *, allowed_errors: int, observed_system_errors: int) -> ErrorBudgetSnapshot:
        if allowed_errors <= 0:
            remaining_ratio = 0.0
        else:
            remaining_ratio = max(0.0, (allowed_errors - observed_system_errors) / allowed_errors)
        if remaining_ratio <= self.exhausted_ratio:
            status = "EXHAUSTED"
        elif remaining_ratio <= self.warning_ratio:
            status = "WARNING"
        elif self._last_status != "HEALTHY" and remaining_ratio < self.recovery_ratio:
            status = self._last_status
        else:
            status = "HEALTHY"
        self._last_status = status
        return ErrorBudgetSnapshot(status, remaining_ratio, observed_system_errors, allowed_errors)
