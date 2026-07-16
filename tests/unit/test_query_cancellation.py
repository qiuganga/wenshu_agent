import asyncio

import pytest

from app.api.schemas.query_schema import QueryRequest
from app.service.query_service import QueryService


class DisconnectRequest:
    def __init__(self, disconnected_after: int = 1):
        self.calls = 0
        self.disconnected_after = disconnected_after

    async def is_disconnected(self):
        self.calls += 1
        return self.calls >= self.disconnected_after


class FakeGraph:
    def __init__(self):
        self.closed = False
        self.cancelled = False

    async def astream(self, **kwargs):
        try:
            while True:
                await asyncio.sleep(1)
                yield {"event": "stage", "message": "late"}
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.closed = True


def make_service(graph):
    return QueryService(None, None, None, None, None, None, agent_graph=graph)


@pytest.mark.asyncio
async def test_disconnect_cancels_graph_and_emits_no_done_or_error():
    graph = FakeGraph()
    service = make_service(graph)
    events = []
    async for event in service.query(QueryRequest(query="hello"), DisconnectRequest()):
        events.append(event)
    assert any("event: started" in event for event in events)
    assert not any("event: done" in event for event in events)
    assert not any("event: error" in event for event in events)
    assert graph.cancelled is True
    assert graph.closed is True


@pytest.mark.asyncio
async def test_cancelled_error_is_not_wrapped():
    class CancelGraph:
        async def astream(self, **kwargs):
            raise asyncio.CancelledError
            yield  # pragma: no cover

    service = make_service(CancelGraph())
    generator = service.query(QueryRequest(query="hello"), None)
    await generator.__anext__()
    with pytest.raises(asyncio.CancelledError):
        await generator.__anext__()
