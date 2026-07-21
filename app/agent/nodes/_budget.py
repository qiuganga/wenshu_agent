from __future__ import annotations

import time
from typing import Any

from app.service.query_lifecycle import QueryLifecycleError


def remaining_budget_seconds(state: Any) -> float | None:
    budget = state.get("budget")
    if not isinstance(budget, dict):
        return None
    deadline = budget.get("deadline")
    if not isinstance(deadline, int | float):
        return None
    remaining = max(0.0, float(deadline) - time.monotonic())
    started_at = budget.get("started_at")
    elapsed = time.monotonic() - float(started_at) if isinstance(started_at, int | float) else 0.0
    state["budget"] = {
        **budget,
        "elapsed": max(0.0, elapsed),
        "remaining": remaining,
    }
    return remaining


def require_budget(state: Any) -> float | None:
    remaining = remaining_budget_seconds(state)
    if remaining is not None and remaining <= 0:
        state["budget_exhausted"] = True
        state["error"] = "Query total timeout"
        state["error_code"] = "QUERY_TOTAL_TIMEOUT"
        state["retryable"] = False
        raise QueryLifecycleError(
            "QUERY_TOTAL_TIMEOUT",
            "Query total timeout",
            {"error_code": "QUERY_TOTAL_TIMEOUT", "retryable": False, "budget_exhausted": True},
            status_code=504,
        )
    return remaining


def effective_timeout(state: Any, configured_timeout: float) -> float:
    remaining = require_budget(state)
    if remaining is None:
        return configured_timeout
    return min(configured_timeout, remaining)
