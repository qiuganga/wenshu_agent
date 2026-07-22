from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.core.telemetry import telemetry_manager


@dataclass(frozen=True)
class ShutdownResult:
    graceful: bool
    duration_seconds: float
    timed_out: bool


class ShutdownManager:
    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        *,
        stop_accepting: Callable[[], Awaitable[Any]],
        cleanup_steps: Iterable[Callable[[], Awaitable[Any]]],
    ) -> ShutdownResult:
        started = time.perf_counter()
        telemetry_manager.increment_counter("shutdown_total")
        await stop_accepting()
        timed_out = False
        try:
            await asyncio.wait_for(self._run_cleanup(cleanup_steps), timeout=self.timeout_seconds)
        except TimeoutError:
            timed_out = True
            telemetry_manager.increment_counter("forced_shutdown_total")
        else:
            telemetry_manager.increment_counter("graceful_shutdown_total")
        duration = time.perf_counter() - started
        telemetry_manager.record_histogram("shutdown_time_seconds", duration)
        return ShutdownResult(graceful=not timed_out, duration_seconds=duration, timed_out=timed_out)

    async def _run_cleanup(self, cleanup_steps: Iterable[Callable[[], Awaitable[Any]]]) -> None:
        for step in cleanup_steps:
            await step()
