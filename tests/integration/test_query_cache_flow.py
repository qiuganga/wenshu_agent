import json
from types import SimpleNamespace

import pytest

from app.api.schemas.query_schema import QueryRequest
from app.cache.key_builder import CacheKeyBuilder
from app.cache.models import CacheLookupResult, CacheScope
from app.cache.service import CacheLookupOutcome
from app.service.query_service import QueryService


def parse_sse(chunks):
    events = []
    for chunk in chunks:
        for block in chunk.strip().split("\n\n"):
            data = [line.removeprefix("data: ") for line in block.splitlines() if line.startswith("data: ")]
            if data:
                events.append(json.loads("\n".join(data)))
    return events


async def collect(service, request):
    return [chunk async for chunk in service.query(request)]


class RecordingGraph:
    def __init__(self):
        self.calls = 0

    async def astream(self, **kwargs):
        self.calls += 1
        yield {
            "event": "result",
            "node": "interpret_result",
            "message": "Result interpreted",
            "final_answer": "fresh answer",
            "result_summary": {"row_count": 1},
        }


class FakeCacheService:
    def __init__(self, outcome=None):
        self.builder = CacheKeyBuilder(redis_prefix="agent")
        self.outcome = outcome
        self.lookup_calls = 0
        self.write_calls = []
        self.lease_released = False

    def build_identity(self, *, query, user_id, **kwargs):
        return self.builder.identity(query, CacheScope(user_id=user_id, data_version="v1"))

    async def lookup(self, identity):
        self.lookup_calls += 1
        if self.outcome is not None:
            return self.outcome
        return CacheLookupOutcome(CacheLookupResult(False, reason="miss"))

    async def acquire_lease(self, identity):
        return "owner"

    async def wait_for_fill(self, identity):
        return None

    async def release_lease(self, identity, owner):
        self.lease_released = True

    async def write(self, **kwargs):
        self.write_calls.append(kwargs)


def service(graph, cache_service):
    return QueryService(None, None, None, None, None, None, agent_graph=graph, cache_service=cache_service)


@pytest.mark.asyncio
async def test_query_service_exact_cache_hit_does_not_start_agent_or_llm():
    hit = CacheLookupOutcome(
        CacheLookupResult(True, "exact", SimpleNamespace(payload={"final_answer": "cached", "result_summary": {}})),
        {"final_answer": "cached", "result_summary": {}, "cache_hit": True, "cache_type": "exact"},
    )
    graph = RecordingGraph()
    cache = FakeCacheService(hit)

    events = parse_sse(await collect(service(graph, cache), QueryRequest(query="hello", request_id="cache-hit-1")))

    assert [event["event"] for event in events] == ["started", "result", "done"]
    assert events[1]["data"]["final_answer"] == "cached"
    assert events[1]["data"]["cache_type"] == "exact"
    assert graph.calls == 0


@pytest.mark.asyncio
async def test_query_service_cache_miss_executes_agent_and_writes_safe_payload():
    graph = RecordingGraph()
    cache = FakeCacheService()

    events = parse_sse(await collect(service(graph, cache), QueryRequest(query="hello", request_id="cache-miss-1")))

    assert [event["event"] for event in events] == ["started", "result", "done"]
    assert graph.calls == 1
    assert len(cache.write_calls) == 1
    assert cache.write_calls[0]["payload"]["final_answer"] == "fresh answer"
    assert cache.lease_released is True


def test_query_cache_identity_is_user_scope_isolated():
    cache = FakeCacheService()

    user_a = cache.build_identity(query="hello", user_id="u1")
    user_b = cache.build_identity(query="hello", user_id="u2")

    assert user_a.query_hash != user_b.query_hash
    assert user_a.scope_hash != user_b.scope_hash
