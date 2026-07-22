from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class SLOEvent:
    timestamp: float
    category: str
    success: bool
    latency_seconds: float = 0


@dataclass(frozen=True)
class SLOSnapshot:
    availability: float
    latency_p95_seconds: float
    status: str
    total_events: int


class SLOManager:
    def __init__(self, *, availability_target: float, latency_p95_seconds: float, window_seconds: float) -> None:
        self.availability_target = availability_target
        self.latency_p95_seconds = latency_p95_seconds
        self.window_seconds = window_seconds
        self._events: deque[SLOEvent] = deque()

    def record(self, *, category: str, success: bool, latency_seconds: float = 0) -> None:
        self._events.append(SLOEvent(time.time(), category, success, latency_seconds))
        self._prune()

    def snapshot(self) -> SLOSnapshot:
        self._prune()
        counted = [event for event in self._events if event.category not in {"business_deny", "security_deny"}]
        if not counted:
            return SLOSnapshot(1.0, 0.0, "HEALTHY", 0)
        successes = sum(1 for event in counted if event.success)
        availability = successes / len(counted)
        latencies = sorted(event.latency_seconds for event in counted)
        index = min(len(latencies) - 1, int(len(latencies) * 0.95))
        p95 = latencies[index]
        status = (
            "HEALTHY" if availability >= self.availability_target and p95 <= self.latency_p95_seconds else "VIOLATED"
        )
        return SLOSnapshot(availability, p95, status, len(counted))

    def _prune(self) -> None:
        cutoff = time.time() - self.window_seconds
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()
