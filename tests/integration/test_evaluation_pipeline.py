import json

import pytest

from app.evaluation.dataset import EvaluationCase, EvaluationDataset
from app.evaluation.runner import EvaluationRunner


class FakeQueryService:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    async def query(self, query_request):
        self.calls.append(query_request)
        yield 'data: {"event":"started","data":{"query_length":5}}\n\n'
        if self.fail:
            yield 'data: {"event":"error","data":{"code":"SQL_SECURITY_FAILED"}}\n\n'
            yield 'data: {"event":"done"}\n\n'
            return
        yield (
            'data: {"event":"result","data":{"final_answer":"销售额最高的地区是华南",'
            '"normalized_sql":"select amount from fact_order",'
            '"result_summary":{"row_count":1,"sample":[{"region":"华南"}]},'
            '"retrieved_documents":["fact_order"]}}\n\n'
        )
        yield 'data: {"event":"done"}\n\n'


@pytest.mark.asyncio
async def test_evaluation_runner_reuses_query_service_and_generates_report():
    dataset = EvaluationDataset(
        version="v1",
        dataset_hash="hash",
        cases=[
            EvaluationCase(
                id="case-1",
                question="查询销售额最高的地区",
                expected_sql="select amount from fact_order",
                expected_answer="华南",
                expected_tables=["fact_order"],
                expected_retrieval=["fact_order"],
            )
        ],
    )
    service = FakeQueryService()

    report = await EvaluationRunner(service).run(dataset)
    payload = report.to_dict()

    assert len(service.calls) == 1
    assert payload["dataset_version"] == "v1"
    assert payload["total_cases"] == 1
    assert payload["success_rate"] == 1.0
    assert payload["sql_accuracy"] == 1.0
    assert json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_evaluation_runner_records_failed_case_without_sensitive_payload():
    dataset = EvaluationDataset(
        version="v1",
        dataset_hash="hash",
        cases=[EvaluationCase(id="case-1", question="blocked")],
    )

    report = await EvaluationRunner(FakeQueryService(fail=True)).run(dataset)
    payload = report.to_dict()

    assert payload["success_rate"] == 0.0
    assert payload["cases"][0]["error_code"] == "SQL_SECURITY_FAILED"
    assert "raw_result" not in json.dumps(payload, ensure_ascii=False)
