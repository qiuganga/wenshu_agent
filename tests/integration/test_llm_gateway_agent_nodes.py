from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.nodes import recall_value as recall_value_module


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def ainvoke_json(self, prompt_name: str, payload: dict[str, object]) -> list[str]:
        self.calls.append((prompt_name, payload))
        return ["extended"]


class FakeValueRepository:
    def __init__(self) -> None:
        self.searched: list[str] = []

    async def search(self, keyword: str) -> list[dict[str, str]]:
        self.searched.append(keyword)
        return [
            {
                "id": f"value:{keyword}",
                "value": keyword,
                "type": "text",
                "column_id": "col-1",
                "column_name": "name",
                "table_id": "table-1",
                "table_name": "orders",
            }
        ]


@pytest.mark.asyncio
async def test_agent_recall_node_uses_llm_gateway(monkeypatch):
    gateway = FakeGateway()
    repository = FakeValueRepository()
    events: list[dict[str, object]] = []
    runtime = SimpleNamespace(
        context={"value_es_repository": repository},
        stream_writer=events.append,
    )

    monkeypatch.setattr(recall_value_module, "llm", gateway)

    result = await recall_value_module.recall_value(
        {"query": "sales by region", "keywords": ["base"]},
        runtime,
    )

    assert gateway.calls == [
        ("extend_keywords_for_value_recall", {"query": "sales by region"}),
    ]
    assert repository.searched == ["base", "extended"]
    assert [value["id"] for value in result["retrieved_values"]] == [
        "value:base",
        "value:extended",
    ]
    assert events[0]["event"] == "stage"
