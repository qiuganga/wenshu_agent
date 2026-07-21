from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import AppException


class QueryLifecycleError(AppException):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None, status_code: int = 429):
        super().__init__(code=code, message=message, details=details, status_code=status_code)


@dataclass(frozen=True)
class AdmissionSnapshot:
    admission_wait_ms: int
    global_active_queries: int
    user_active_queries: int


@dataclass(frozen=True)
class AdmissionLease:
    user_id: str
    key: str
    wait_ms: int


class QueryAdmissionController:
    def __init__(self, *, max_global: int, max_per_user: int, timeout_seconds: float):
        self.max_global = max_global
        self.max_per_user = max_per_user
        self.timeout_seconds = timeout_seconds
        self._condition = asyncio.Condition()
        self._global_active = 0
        self._user_active: dict[str, int] = {}
        self._active_keys: set[str] = set()
        self._accepting = True
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def accepting(self) -> bool:
        return self._accepting

    def snapshot_for(self, user_id: str, wait_ms: int = 0) -> AdmissionSnapshot:
        return AdmissionSnapshot(
            admission_wait_ms=wait_ms,
            global_active_queries=self._global_active,
            user_active_queries=self._user_active.get(user_id, 0),
        )

    async def acquire(self, *, user_id: str, key: str) -> AdmissionLease:
        started = time.perf_counter()
        async with self._condition:
            if not self._accepting:
                raise QueryLifecycleError(
                    "SERVICE_SHUTTING_DOWN",
                    "Service is shutting down",
                    {"error_code": "SERVICE_SHUTTING_DOWN", "retryable": False},
                    status_code=503,
                )
            if key in self._active_keys:
                raise QueryLifecycleError(
                    "DUPLICATE_REQUEST",
                    "Duplicate request",
                    {"error_code": "DUPLICATE_REQUEST", "retryable": False, "duplicate_request": True},
                )

            deadline = started + self.timeout_seconds
            while True:
                if self._global_active < self.max_global and self._user_active.get(user_id, 0) < self.max_per_user:
                    self._global_active += 1
                    self._user_active[user_id] = self._user_active.get(user_id, 0) + 1
                    self._active_keys.add(key)
                    return AdmissionLease(user_id=user_id, key=key, wait_ms=int((time.perf_counter() - started) * 1000))

                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    details = self._failure_details(user_id, "QUERY_ADMISSION_TIMEOUT")
                    raise QueryLifecycleError(
                        details["error_code"],
                        "Query admission timed out",
                        details,
                    )
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except TimeoutError as exc:
                    details = self._failure_details(user_id, "QUERY_ADMISSION_TIMEOUT")
                    raise QueryLifecycleError(
                        details["error_code"],
                        "Query admission timed out",
                        details,
                    ) from exc

    def _failure_details(self, user_id: str, error_code: str) -> dict[str, Any]:
        if self._global_active >= self.max_global:
            error_code = "QUERY_CONCURRENCY_LIMIT"
        if self._user_active.get(user_id, 0) >= self.max_per_user:
            error_code = "USER_QUERY_CONCURRENCY_LIMIT"
        return {
            "error_code": error_code,
            "retryable": False,
            "global_active_queries": self._global_active,
            "user_active_queries": self._user_active.get(user_id, 0),
        }

    async def release(self, lease: AdmissionLease | None) -> None:
        if lease is None:
            return
        async with self._condition:
            if lease.key not in self._active_keys:
                return
            self._active_keys.remove(lease.key)
            self._global_active = max(0, self._global_active - 1)
            user_count = max(0, self._user_active.get(lease.user_id, 0) - 1)
            if user_count:
                self._user_active[lease.user_id] = user_count
            else:
                self._user_active.pop(lease.user_id, None)
            self._condition.notify_all()

    def register_task(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def begin_shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        async with self._condition:
            self._accepting = False
            self._condition.notify_all()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout_seconds)
            except TimeoutError:
                pass

    async def reset(self) -> None:
        async with self._condition:
            self._accepting = True
            self._global_active = 0
            self._user_active.clear()
            self._active_keys.clear()
            self._condition.notify_all()


@dataclass
class DedupEntry:
    request_id_hash: str
    created_at: float
    status: str


@dataclass(frozen=True)
class DedupToken:
    request_id_hash: str


class RequestDedupRegistry:
    def __init__(self, *, ttl_seconds: float, max_entries: int):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._lock = asyncio.Lock()
        self._entries: OrderedDict[str, DedupEntry] = OrderedDict()

    @staticmethod
    def hash_request_id(request_id: str) -> str:
        return hashlib.sha256(request_id.encode("utf-8")).hexdigest()

    async def register(self, request_id: str) -> DedupToken:
        request_id_hash = self.hash_request_id(request_id)
        now = time.monotonic()
        async with self._lock:
            self._prune_locked(now)
            entry = self._entries.get(request_id_hash)
            if entry is not None:
                raise QueryLifecycleError(
                    "DUPLICATE_REQUEST",
                    "Duplicate request",
                    {"error_code": "DUPLICATE_REQUEST", "retryable": False, "duplicate_request": True},
                )
            self._entries[request_id_hash] = DedupEntry(
                request_id_hash=request_id_hash,
                created_at=now,
                status="active",
            )
            self._evict_locked()
            return DedupToken(request_id_hash=request_id_hash)

    async def complete(self, token: DedupToken | None, status: str) -> None:
        if token is None:
            return
        async with self._lock:
            entry = self._entries.get(token.request_id_hash)
            if entry is not None:
                entry.status = status
                self._entries.move_to_end(token.request_id_hash)

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

    def _prune_locked(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if now - entry.created_at >= self.ttl_seconds]
        for key in expired:
            self._entries.pop(key, None)

    def _evict_locked(self) -> None:
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)


class QueryExecutionBudget:
    def __init__(self, *, total_timeout_seconds: float, started_at: float | None = None):
        self.started_at = started_at if started_at is not None else time.monotonic()
        self.deadline = self.started_at + total_timeout_seconds

    @property
    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    @property
    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def remaining_or_raise(self) -> float:
        remaining = self.remaining
        if remaining <= 0:
            raise QueryLifecycleError(
                "QUERY_TOTAL_TIMEOUT",
                "Query total timeout",
                {"error_code": "QUERY_TOTAL_TIMEOUT", "retryable": False, "budget_exhausted": True},
                status_code=504,
            )
        return remaining

    def local_timeout(self, configured_timeout: float) -> float:
        return min(configured_timeout, self.remaining_or_raise())

    def summary(self) -> dict[str, float]:
        return {
            "started_at": self.started_at,
            "deadline": self.deadline,
            "elapsed": self.elapsed,
            "remaining": self.remaining,
        }


CRITICAL_EVENTS = {"error", "final", "cancelled"}


class LifecycleSSEQueue:
    def __init__(self, *, maxsize: int, put_timeout_seconds: float):
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self.put_timeout_seconds = put_timeout_seconds
        self.closed = False
        self.dropped_events = 0
        self._emitted_error = False
        self._emitted_final = False
        self._emitted_cancelled = False

    async def put_graph_event(self, event: dict[str, Any]) -> None:
        if self.closed:
            raise QueryLifecycleError(
                "SSE_STREAM_CLOSED",
                "SSE stream is closed",
                {"error_code": "SSE_STREAM_CLOSED", "retryable": False},
            )
        event_type = str(event.get("event", "stage"))
        is_final = event_type == "final" or "final_answer" in event
        if event_type == "error":
            if self._emitted_error:
                return
            self._emitted_error = True
        if is_final:
            if self._emitted_error or self._emitted_final or self._emitted_cancelled:
                return
            self._emitted_final = True
        if event_type == "cancelled":
            if self._emitted_cancelled:
                return
            self._emitted_cancelled = True
        if self._emitted_cancelled and event_type not in CRITICAL_EVENTS:
            self.dropped_events += 1
            return
        critical = event_type in CRITICAL_EVENTS or is_final
        if not critical and self.queue.full():
            self.dropped_events += 1
            return
        try:
            await asyncio.wait_for(self.queue.put(event), timeout=self.put_timeout_seconds if critical else None)
        except TimeoutError as exc:
            raise QueryLifecycleError(
                "SSE_BACKPRESSURE_TIMEOUT",
                "SSE backpressure timeout",
                {"error_code": "SSE_BACKPRESSURE_TIMEOUT", "retryable": False},
            ) from exc

    async def put_exception(self, exc: BaseException) -> None:
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
        await asyncio.wait_for(self.queue.put(exc), timeout=self.put_timeout_seconds)
