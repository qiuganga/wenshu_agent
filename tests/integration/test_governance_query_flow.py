import json

import pytest

from app.api.schemas.query_schema import QueryRequest
from app.service.query_service import QueryService


class CapturingGraph:
    def __init__(self) -> None:
        self.state = None

    async def astream(self, **kwargs):
        self.state = kwargs["input"]
        yield {
            "event": "result",
            "node": "interpret_result",
            "message": "Result interpreted",
            "final_answer": "ok",
            "result_summary": {"row_count": 1},
        }


def parse_sse_events(chunks: list[str]) -> list[dict]:
    events = []
    for chunk in chunks:
        for block in chunk.strip().split("\n\n"):
            data_lines = [line.removeprefix("data: ") for line in block.splitlines() if line.startswith("data: ")]
            if data_lines:
                events.append(json.loads("\n".join(data_lines)))
    return events


@pytest.mark.asyncio
async def test_governance_context_is_added_to_query_state_without_sse_protocol_change() -> None:
    graph = CapturingGraph()
    service = QueryService(None, None, None, None, None, None, agent_graph=graph)

    chunks = [chunk async for chunk in service.query(QueryRequest(query="查询销售趋势并分析原因"), None)]
    events = parse_sse_events(chunks)

    assert [event["event"] for event in events] == ["started", "result", "done"]
    assert graph.state["governance_context"]["user_hash"]
    assert graph.state["complexity"]["complexity_level"] == "COMPLEX"
    assert "query" not in graph.state["governance_context"]
    assert "prompt" not in json.dumps(graph.state["governance_context"], ensure_ascii=False)
