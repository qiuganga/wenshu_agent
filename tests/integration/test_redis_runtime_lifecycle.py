import asyncio
import json
import uuid
from contextlib import suppress
from typing import Any

import pytest

from app.api.schemas.query_schema import QueryRequest
from app.clients.redis_client_manager import redis_client_manager
from app.service import query_service as query_service_module
from app.service.query_lifecycle import QueryLifecycleError, RedisQueryAdmissionController, RedisRequestDedupRegistry
from app.service.query_service import QueryService

pytestmark = pytest.mark.asyncio


class FinalGraph:
    def __init__(self):
        self.starts = 0

    async def astream(self, **kwargs: Any):
        self.starts += 1
        yield {"event": "result", "node": "fake", "message": "done", "final_answer": "ok"}


class BlockingGraph:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False

    async def astream(self, **kwargs: Any):
        self.started.set()
        try:
            await self.release.wait()
            yield {"event": "result", "node": "fake", "message": "done", "final_answer": "ok"}
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class DisconnectRequest:
    def __init__(self):
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls >= 2


async def live_redis():
    redis_client_manager.init()
    client = redis_client_manager.client
    if client is None:
        pytest.skip("Redis client is not initialized")
    try:
        await client.ping()
    except Exception as exc:
        await redis_client_manager.close()
        pytest.skip(f"Redis is not available: {type(exc).__name__}")
    return client


async def scan(client, pattern: str) -> list[str]:
    cursor = 0
    keys: list[str] = []
    while True:
        cursor, batch = await client.scan(cursor=cursor, match=pattern, count=100)
        keys.extend(batch)
        if cursor == 0:
            return sorted(keys)


async def delete_prefix(client, prefix: str) -> None:
    keys = await scan(client, f"{prefix}:*")
    if keys:
        await client.delete(*keys)


def service_for(graph):
    return QueryService(None, None, None, None, None, None, agent_graph=graph)


async def collect(service: QueryService, request: QueryRequest, disconnect_request=None) -> list[dict[str, Any]]:
    events = []
    async for chunk in service.query(request, disconnect_request):
        for part in chunk.strip().split("\n\n"):
            data_line = next((line for line in part.splitlines() if line.startswith("data: ")), None)
            if data_line:
                events.append(json.loads(data_line[6:]))
    return events


def event_names(events: list[dict[str, Any]]) -> list[str]:
    return [event["event"] for event in events]


def install_lifecycle(monkeypatch, client, prefix: str, *, ttl_seconds: float = 0.5, max_global=2, max_per_user=1):
    controller = RedisQueryAdmissionController(
        max_global=max_global,
        max_per_user=max_per_user,
        timeout_seconds=0.03,
        redis_client=lambda: client,
        key_prefix=prefix,
        lease_ttl_seconds=1,
    )
    registry = RedisRequestDedupRegistry(
        ttl_seconds=ttl_seconds,
        max_entries=100,
        redis_client=lambda: client,
        key_prefix=prefix,
    )
    monkeypatch.setattr(query_service_module, "admission_controller", controller)
    monkeypatch.setattr(query_service_module, "request_dedup_registry", registry)
    return controller, registry


async def test_query_service_dedup_uses_live_redis_and_ttl(monkeypatch):
    client = await live_redis()
    prefix = f"wenshu-agent-test:{uuid.uuid4().hex}"
    await delete_prefix(client, prefix)
    try:
        _, registry = install_lifecycle(monkeypatch, client, prefix, ttl_seconds=0.05)
        graph = FinalGraph()
        service = service_for(graph)

        first = await collect(service, QueryRequest(query="hello", request_id="same", user_id="u1"))
        keys = await scan(client, f"{prefix}:dedup:*")
        ttl_values = [await client.pttl(key) for key in keys]
        second = await collect(service, QueryRequest(query="hello", request_id="same", user_id="u1"))

        assert event_names(first) == ["started", "result", "done"]
        assert event_names(second) == ["started", "error", "done"]
        assert "DUPLICATE_REQUEST" in json.dumps(second)
        assert graph.starts == 1
        assert keys
        assert all(ttl > 0 for ttl in ttl_values)

        await asyncio.sleep(0.08)
        third = await collect(service, QueryRequest(query="hello", request_id="same", user_id="u1"))
        assert event_names(third) == ["started", "result", "done"]
        assert graph.starts == 2
        assert await client.get(registry._key(registry.hash_request_id("same"))) == "completed"
    finally:
        await delete_prefix(client, prefix)
        await redis_client_manager.close()


async def test_live_redis_admission_counters_release_and_limits():
    client = await live_redis()
    prefix = f"wenshu-agent-test:{uuid.uuid4().hex}"
    await delete_prefix(client, prefix)
    try:
        global_controller = RedisQueryAdmissionController(
            max_global=1,
            max_per_user=1,
            timeout_seconds=0.02,
            redis_client=lambda: client,
            key_prefix=f"{prefix}:global",
            lease_ttl_seconds=1,
        )
        lease = await global_controller.acquire(user_id="u1", key="k1")
        assert await client.zcard(f"{prefix}:global:admission:global") == 1
        with pytest.raises(QueryLifecycleError) as global_exc:
            await global_controller.acquire(user_id="u2", key="k2")
        assert global_exc.value.code == "QUERY_CONCURRENCY_LIMIT"
        await global_controller.release(lease)
        assert await client.zcard(f"{prefix}:global:admission:global") == 0

        user_controller = RedisQueryAdmissionController(
            max_global=2,
            max_per_user=1,
            timeout_seconds=0.02,
            redis_client=lambda: client,
            key_prefix=f"{prefix}:user",
            lease_ttl_seconds=1,
        )
        first = await user_controller.acquire(user_id="u1", key="k1")
        second = await user_controller.acquire(user_id="u2", key="k2")
        with pytest.raises(QueryLifecycleError) as user_exc:
            await user_controller.acquire(user_id="u1", key="k3")
        assert user_exc.value.code == "USER_QUERY_CONCURRENCY_LIMIT"
        await user_controller.release(first)
        await user_controller.release(second)
        assert await client.zcard(f"{prefix}:user:admission:global") == 0
    finally:
        await delete_prefix(client, prefix)
        await delete_prefix(client, f"{prefix}:global")
        await delete_prefix(client, f"{prefix}:user")
        await redis_client_manager.close()


async def test_query_service_disconnect_and_shutdown_release_live_redis(monkeypatch):
    client = await live_redis()
    prefix = f"wenshu-agent-test:{uuid.uuid4().hex}"
    await delete_prefix(client, prefix)
    original_interval = query_service_module.app_config.agent.disconnect_poll_interval_seconds
    try:
        controller, registry = install_lifecycle(monkeypatch, client, prefix)
        monkeypatch.setattr(query_service_module.app_config.agent, "disconnect_poll_interval_seconds", 0.01)

        disconnect_graph = BlockingGraph()
        disconnect_events = await collect(
            service_for(disconnect_graph),
            QueryRequest(query="hello", request_id="disconnect-1", user_id="u1"),
            DisconnectRequest(),
        )
        disconnect_key = registry._key(registry.hash_request_id("disconnect-1"))
        assert event_names(disconnect_events) == ["started"]
        assert disconnect_graph.cancelled is True
        assert await client.zcard(f"{prefix}:admission:global") == 0
        assert await client.get(disconnect_key) == "cancelled"

        shutdown_graph = BlockingGraph()
        task = asyncio.create_task(
            collect(
                service_for(shutdown_graph), QueryRequest(query="hello", request_id="shutdown-active", user_id="u1")
            )
        )
        await asyncio.wait_for(shutdown_graph.started.wait(), timeout=1)
        assert await client.zcard(f"{prefix}:admission:global") == 1
        await controller.begin_shutdown(timeout_seconds=0.2)
        with suppress(asyncio.CancelledError):
            await task
        assert shutdown_graph.cancelled is True
        assert await client.zcard(f"{prefix}:admission:global") == 0

        rejected = await collect(
            service_for(FinalGraph()),
            QueryRequest(query="hello", request_id="shutdown-reject", user_id="u1"),
        )
        assert event_names(rejected) == ["started", "error", "done"]
        assert "SERVICE_SHUTTING_DOWN" in json.dumps(rejected)
    finally:
        query_service_module.app_config.agent.disconnect_poll_interval_seconds = original_interval
        await delete_prefix(client, prefix)
        await redis_client_manager.close()
