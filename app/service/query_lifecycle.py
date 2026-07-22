from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable
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


ADMISSION_ACQUIRE_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
if redis.call('EXISTS', KEYS[3]) == 1 then
  return {'duplicate', redis.call('ZCARD', KEYS[1]), redis.call('ZCARD', KEYS[2])}
end
local global_count = tonumber(redis.call('ZCARD', KEYS[1]))
local user_count = tonumber(redis.call('ZCARD', KEYS[2]))
if user_count >= tonumber(ARGV[4]) then
  return {'user_limit', global_count, user_count}
end
if global_count >= tonumber(ARGV[3]) then
  return {'global_limit', global_count, user_count}
end
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[6])
redis.call('ZADD', KEYS[2], ARGV[2], ARGV[6])
redis.call('SET', KEYS[3], ARGV[5], 'PX', ARGV[7])
local key_ttl_seconds = math.max(1, math.ceil(tonumber(ARGV[7]) / 1000) * 2)
redis.call('EXPIRE', KEYS[1], key_ttl_seconds)
redis.call('EXPIRE', KEYS[2], key_ttl_seconds)
return {'ok', global_count + 1, user_count + 1}
"""

ADMISSION_RELEASE_LUA = """
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('DEL', KEYS[3])
return {redis.call('ZCARD', KEYS[1]), redis.call('ZCARD', KEYS[2])}
"""

ADMISSION_SNAPSHOT_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
return {redis.call('ZCARD', KEYS[1]), redis.call('ZCARD', KEYS[2])}
"""


class RedisQueryAdmissionController:
    def __init__(
        self,
        *,
        max_global: int,
        max_per_user: int,
        timeout_seconds: float,
        redis_client: Callable[[], Any],
        key_prefix: str,
        lease_ttl_seconds: float,
    ):
        self.max_global = max_global
        self.max_per_user = max_per_user
        self.timeout_seconds = timeout_seconds
        self.redis_client = redis_client
        self.key_prefix = key_prefix.rstrip(":")
        self.lease_ttl_seconds = lease_ttl_seconds
        self._fallback = QueryAdmissionController(
            max_global=max_global,
            max_per_user=max_per_user,
            timeout_seconds=timeout_seconds,
        )
        self._accepting = True
        self._tasks: set[asyncio.Task[Any]] = set()
        self._last_snapshots: dict[str, AdmissionSnapshot] = {}

    @property
    def accepting(self) -> bool:
        return self._accepting

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _global_key(self) -> str:
        return f"{self.key_prefix}:admission:global"

    def _user_key(self, user_id: str) -> str:
        return f"{self.key_prefix}:admission:user:{self._hash(user_id)}"

    def _lease_key(self, member: str) -> str:
        return f"{self.key_prefix}:admission:lease:{member}"

    def _client(self) -> Any | None:
        return self.redis_client()

    def snapshot_for(self, user_id: str, wait_ms: int = 0) -> AdmissionSnapshot:
        return self._last_snapshots.get(
            user_id,
            AdmissionSnapshot(admission_wait_ms=wait_ms, global_active_queries=0, user_active_queries=0),
        )

    async def acquire(self, *, user_id: str, key: str) -> AdmissionLease:
        client = self._client()
        if client is None:
            return await self._fallback.acquire(user_id=user_id, key=key)
        if not self._accepting:
            raise QueryLifecycleError(
                "SERVICE_SHUTTING_DOWN",
                "Service is shutting down",
                {"error_code": "SERVICE_SHUTTING_DOWN", "retryable": False},
                status_code=503,
            )

        started = time.perf_counter()
        member = self._hash(key)
        deadline = started + self.timeout_seconds
        ttl_ms = max(1, int(self.lease_ttl_seconds * 1000))
        while True:
            now_ms = int(time.time() * 1000)
            expires_at_ms = now_ms + ttl_ms
            result = await client.eval(
                ADMISSION_ACQUIRE_LUA,
                3,
                self._global_key(),
                self._user_key(user_id),
                self._lease_key(member),
                now_ms,
                expires_at_ms,
                self.max_global,
                self.max_per_user,
                self._hash(user_id),
                member,
                ttl_ms,
            )
            status = str(result[0])
            global_active = int(result[1])
            user_active = int(result[2])
            wait_ms = int((time.perf_counter() - started) * 1000)
            self._last_snapshots[user_id] = AdmissionSnapshot(wait_ms, global_active, user_active)
            if status == "ok":
                return AdmissionLease(user_id=user_id, key=key, wait_ms=wait_ms)
            if status == "duplicate":
                raise QueryLifecycleError(
                    "DUPLICATE_REQUEST",
                    "Duplicate request",
                    {"error_code": "DUPLICATE_REQUEST", "retryable": False, "duplicate_request": True},
                )

            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                error_code = "QUERY_CONCURRENCY_LIMIT" if status == "global_limit" else "USER_QUERY_CONCURRENCY_LIMIT"
                raise QueryLifecycleError(
                    error_code,
                    "Query admission timed out",
                    {
                        "error_code": error_code,
                        "retryable": False,
                        "global_active_queries": global_active,
                        "user_active_queries": user_active,
                    },
                )
            await asyncio.sleep(min(0.05, remaining))

    async def release(self, lease: AdmissionLease | None) -> None:
        if lease is None:
            return
        client = self._client()
        if client is None:
            await self._fallback.release(lease)
            return
        member = self._hash(lease.key)
        result = await client.eval(
            ADMISSION_RELEASE_LUA,
            3,
            self._global_key(),
            self._user_key(lease.user_id),
            self._lease_key(member),
            member,
        )
        self._last_snapshots[lease.user_id] = AdmissionSnapshot(
            admission_wait_ms=lease.wait_ms,
            global_active_queries=int(result[0]),
            user_active_queries=int(result[1]),
        )

    def register_task(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def begin_shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        self._accepting = False
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout_seconds)
            except TimeoutError:
                pass
        await self._fallback.begin_shutdown(timeout_seconds=timeout_seconds)

    async def reset(self) -> None:
        self._accepting = True
        self._last_snapshots.clear()
        await self._fallback.reset()


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


DEDUP_REGISTER_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then
  return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
return 1
"""


class RedisRequestDedupRegistry:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        redis_client: Callable[[], Any],
        key_prefix: str,
    ):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.redis_client = redis_client
        self.key_prefix = key_prefix.rstrip(":")
        self._fallback = RequestDedupRegistry(ttl_seconds=ttl_seconds, max_entries=max_entries)

    @staticmethod
    def hash_request_id(request_id: str) -> str:
        return RequestDedupRegistry.hash_request_id(request_id)

    def _key(self, request_id_hash: str) -> str:
        return f"{self.key_prefix}:dedup:{request_id_hash}"

    def _client(self) -> Any | None:
        return self.redis_client()

    async def register(self, request_id: str) -> DedupToken:
        client = self._client()
        if client is None:
            return await self._fallback.register(request_id)
        request_id_hash = self.hash_request_id(request_id)
        ttl_ms = max(1, int(self.ttl_seconds * 1000))
        created = await client.eval(DEDUP_REGISTER_LUA, 1, self._key(request_id_hash), "active", ttl_ms)
        if int(created) != 1:
            raise QueryLifecycleError(
                "DUPLICATE_REQUEST",
                "Duplicate request",
                {"error_code": "DUPLICATE_REQUEST", "retryable": False, "duplicate_request": True},
            )
        return DedupToken(request_id_hash=request_id_hash)

    async def complete(self, token: DedupToken | None, status: str) -> None:
        if token is None:
            return
        client = self._client()
        if client is None:
            await self._fallback.complete(token, status)
            return
        key = self._key(token.request_id_hash)
        if await client.exists(key):
            await client.set(key, status, keepttl=True)

    async def clear(self) -> None:
        await self._fallback.clear()


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
