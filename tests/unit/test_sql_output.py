import pytest
from langchain_core.prompts import PromptTemplate

from app.agent.nodes._sql_output import invoke_sql_chain, parse_sql_generation_output, validate_generated_sql
from app.core.exceptions import SQLValidationError


class FakeStructuredLLM:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, payload):
        return self.result


class FakeFallbackLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.payloads = []

    def with_structured_output(self, schema):
        raise NotImplementedError

    async def ainvoke(self, payload):
        self.payloads.append(payload)
        return self.outputs.pop(0)


@pytest.mark.asyncio
async def test_native_structured_output_success():
    prompt = PromptTemplate(template="{query}", input_variables=["query"])
    sql = await invoke_sql_chain(prompt, FakeStructuredLLM({"sql": "select order_id from fact_order"}), {"query": "q"})
    assert sql == "select order_id from fact_order"


@pytest.mark.asyncio
async def test_fallback_parser_success():
    prompt = PromptTemplate(template="{query}", input_variables=["query"])
    sql = await invoke_sql_chain(prompt, FakeFallbackLLM(['{"sql":"select order_id from fact_order"}']), {"query": "q"})
    assert sql == "select order_id from fact_order"


@pytest.mark.asyncio
async def test_retry_includes_previous_error_feedback():
    prompt = PromptTemplate(template="{query}", input_variables=["query"])
    llm = FakeFallbackLLM(["not json", '{"sql":"select order_id from fact_order"}'])
    sql = await invoke_sql_chain(prompt, llm, {"query": "q"})
    assert sql.startswith("select")
    assert llm.payloads[1]["parse_error"] == "LLM_SQL_PARSE_FAILED"
    assert "previous_output" in llm.payloads[1]


def test_parse_sql_generation_json():
    parsed = parse_sql_generation_output('{"sql":"select order_id from fact_order"}')
    assert parsed.sql == "select order_id from fact_order"


@pytest.mark.parametrize("text", ["select * from t", "{}", '{"sql":""}', '{"sql": 1}'])
def test_parse_invalid_sql_output_rejected(text):
    with pytest.raises(SQLValidationError):
        validate_generated_sql(parse_sql_generation_output(text))


def test_markdown_json_supported():
    parsed = parse_sql_generation_output('```json\n{"sql":"select order_id from fact_order"}\n```')
    assert validate_generated_sql(parsed) == "select order_id from fact_order"


@pytest.mark.asyncio
async def test_retries_exceeded():
    prompt = PromptTemplate(template="{query}", input_variables=["query"])
    with pytest.raises(SQLValidationError) as exc:
        await invoke_sql_chain(prompt, FakeFallbackLLM(["bad", "bad", "bad", "bad"]), {"query": "q"})
    assert exc.value.details["code"] == "LLM_SQL_RETRIES_EXCEEDED"
