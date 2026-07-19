from types import SimpleNamespace

import pytest

from app.agent.nodes import filter_table as filter_table_module
from app.agent.nodes.filter_table import _filter_selected_tables, filter_table
from app.agent.schemas.query_plan import TableSelectionResult


class FakeStructuredLLM:
    def __init__(self, result):
        self.result = result
        self.payloads = []

    async def ainvoke(self, payload):
        self.payloads.append(payload)
        return self.result


class FakeLLM:
    def __init__(self, result):
        self.structured_llm = FakeStructuredLLM(result)

    def with_structured_output(self, schema):
        assert schema is TableSelectionResult
        return self.structured_llm


def _table(name):
    return {
        "name": name,
        "role": "dimension",
        "description": f"{name} description",
        "columns": [{"name": "id"}, {"name": "name"}],
    }


def test_filter_selected_tables_is_deterministic_and_bounded():
    table_infos = [_table("orders"), _table("users"), _table("regions")]
    selection = TableSelectionResult(
        selected_tables=[
            "regions",
            "missing",
            "orders",
            "orders",
            "users",
        ]
    )

    filtered = _filter_selected_tables(table_infos, selection, max_tables=2)

    assert [table["name"] for table in filtered] == ["orders", "users"]
    assert filtered[0] is table_infos[0]
    assert filtered[1] is table_infos[1]


def test_filter_selected_tables_allows_empty_result():
    filtered = _filter_selected_tables([_table("orders")], TableSelectionResult(selected_tables=[]), max_tables=10)

    assert filtered == []


def test_filter_selected_tables_keeps_first_duplicate_candidate():
    first_orders = _table("orders")
    duplicate_orders = _table("orders")
    users = _table("users")
    regions = _table("regions")
    table_infos = [first_orders, duplicate_orders, users, regions]
    selection = TableSelectionResult(selected_tables=["orders", "users", "regions"])

    filtered = _filter_selected_tables(table_infos, selection, max_tables=2)

    assert [table["name"] for table in filtered] == ["orders", "users"]
    assert filtered[0] is first_orders
    assert filtered[0] is not duplicate_orders
    assert filtered[1] is users


@pytest.mark.asyncio
async def test_filter_table_uses_structured_output_and_discards_unknown_tables(monkeypatch):
    fake_llm = FakeLLM({"selected_tables": ["missing", "regions", "orders", "orders"]})
    monkeypatch.setattr(filter_table_module, "llm", fake_llm)
    monkeypatch.setattr(filter_table_module.app_config.agent, "max_candidate_tables", 10)
    runtime = SimpleNamespace(stream_writer=lambda event: None)
    table_infos = [_table("orders"), _table("regions")]

    result = await filter_table({"query": "sales by region", "table_infos": table_infos}, runtime)

    assert [table["name"] for table in result["table_infos"]] == ["orders", "regions"]
    assert result["table_infos"][0]["columns"] == table_infos[0]["columns"]
    assert fake_llm.structured_llm.payloads
