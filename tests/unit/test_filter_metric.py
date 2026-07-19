from types import SimpleNamespace

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agent.nodes import filter_metric as filter_metric_module
from app.agent.nodes.filter_metric import _filter_selected_metrics, filter_metric
from app.agent.schemas.query_plan import MetricSelectionResult


class FakeStructuredLLM:
    def __init__(self, result):
        self.result = result
        self.payloads = []

    async def ainvoke(self, payload):
        self.payloads.append(payload)
        return self.result


class FakeStructuredOutputLLM:
    def __init__(self, result):
        self.structured_llm = FakeStructuredLLM(result)

    def with_structured_output(self, schema):
        assert schema is MetricSelectionResult
        return self.structured_llm


def _metric(name):
    return {
        "name": name,
        "description": f"{name} description",
        "relevant_columns": ["fact_order.order_amount"],
        "alias": [f"{name} alias"],
    }


def test_filter_selected_metrics_is_deterministic_and_bounded():
    metric_infos = [_metric("GMV"), _metric("AOV"), _metric("COUNT")]
    selection = MetricSelectionResult(selected_metrics=["COUNT", "missing", "GMV", "GMV", "AOV"])

    filtered = _filter_selected_metrics(metric_infos, selection, max_metrics=2)

    assert [metric["name"] for metric in filtered] == ["GMV", "AOV"]
    assert filtered[0] is metric_infos[0]
    assert filtered[1] is metric_infos[1]


def test_filter_selected_metrics_allows_empty_result():
    filtered = _filter_selected_metrics([_metric("GMV")], MetricSelectionResult(selected_metrics=[]), max_metrics=10)

    assert filtered == []


def test_filter_selected_metrics_keeps_first_duplicate_candidate():
    first_gmv = _metric("GMV")
    duplicate_gmv = _metric("GMV")
    aov = _metric("AOV")
    count = _metric("COUNT")
    metric_infos = [first_gmv, duplicate_gmv, aov, count]
    selection = MetricSelectionResult(selected_metrics=["GMV", "AOV", "COUNT"])

    filtered = _filter_selected_metrics(metric_infos, selection, max_metrics=2)

    assert [metric["name"] for metric in filtered] == ["GMV", "AOV"]
    assert filtered[0] is first_gmv
    assert filtered[0] is not duplicate_gmv
    assert filtered[1] is aov


@pytest.mark.asyncio
async def test_filter_metric_uses_structured_output_and_preserves_original_definition(monkeypatch):
    fake_llm = FakeStructuredOutputLLM({"selected_metrics": ["missing", "AOV", "GMV", "GMV"]})
    monkeypatch.setattr(filter_metric_module, "llm", fake_llm)
    monkeypatch.setattr(filter_metric_module.app_config.agent, "max_candidate_metrics", 10)
    runtime = SimpleNamespace(stream_writer=lambda event: None)
    metric_infos = [_metric("GMV"), _metric("AOV")]

    result = await filter_metric({"query": "sales", "metric_infos": metric_infos}, runtime)

    assert [metric["name"] for metric in result["metric_infos"]] == ["GMV", "AOV"]
    assert result["metric_infos"][0] is metric_infos[0]
    assert fake_llm.structured_llm.payloads


@pytest.mark.asyncio
async def test_filter_metric_fallback_parser(monkeypatch):
    fake_llm = RunnableLambda(lambda payload: AIMessage(content='{"selected_metrics":["AOV","missing"]}'))
    monkeypatch.setattr(filter_metric_module, "llm", fake_llm)
    runtime = SimpleNamespace(stream_writer=lambda event: None)
    metric_infos = [_metric("GMV"), _metric("AOV")]

    result = await filter_metric({"query": "average order", "metric_infos": metric_infos}, runtime)

    assert [metric["name"] for metric in result["metric_infos"]] == ["AOV"]


@pytest.mark.asyncio
async def test_filter_metric_fallback_parse_failure_raises(monkeypatch):
    fake_llm = RunnableLambda(lambda payload: AIMessage(content="not json"))
    monkeypatch.setattr(filter_metric_module, "llm", fake_llm)
    runtime = SimpleNamespace(stream_writer=lambda event: None)

    with pytest.raises(OutputParserException):
        await filter_metric({"query": "sales", "metric_infos": [_metric("GMV")]}, runtime)
