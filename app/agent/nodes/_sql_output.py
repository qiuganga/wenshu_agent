from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import ValidationError

from app.config.app_config import app_config
from app.core.exceptions import SQLValidationError
from app.security.sql_security import SQLGenerationResult

SQL_OUTPUT_PARSER = PydanticOutputParser(pydantic_object=SQLGenerationResult)


def sql_format_instructions() -> str:
    return SQL_OUTPUT_PARSER.get_format_instructions()


def _strip_code_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lower().startswith("sql"):
            value = value[3:]
        if value.lower().startswith("json"):
            value = value[4:]
    return value.strip()


def _extract_json(text: str) -> dict[str, Any]:
    clean = _strip_code_fence(text)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise SQLValidationError("LLM SQL output is not valid JSON", {"code": "LLM_SQL_PARSE_FAILED"}) from exc
    if not isinstance(value, dict):
        raise SQLValidationError("LLM SQL output must be a JSON object", {"code": "LLM_SQL_PARSE_FAILED"})
    return value


def parse_sql_generation_output(text: str) -> SQLGenerationResult:
    try:
        return SQL_OUTPUT_PARSER.parse(text)
    except Exception:
        try:
            return SQLGenerationResult.model_validate(_extract_json(text))
        except (ValidationError, SQLValidationError) as exc:
            raise SQLValidationError("LLM SQL output parse failed", {"code": "LLM_SQL_PARSE_FAILED"}) from exc


def validate_generated_sql(value: SQLGenerationResult) -> str:
    sql = _strip_code_fence(value.sql)
    if not sql:
        raise SQLValidationError("LLM generated empty SQL", {"code": "LLM_SQL_EMPTY"})
    lowered = sql.lower()
    explanation_markers = ("```", "select??", "??", "??", "sql:", "??")
    if any(marker in lowered for marker in explanation_markers):
        raise SQLValidationError("LLM output contains explanation instead of pure SQL", {"code": "LLM_SQL_NOT_PURE"})
    return sql


async def invoke_sql_chain(prompt: PromptTemplate, llm: Any, payload: dict[str, Any]) -> str:
    chain = prompt | llm
    last_error: Exception | None = None
    attempts = app_config.agent.llm_output_parse_retries + 1
    for _ in range(attempts):
        try:
            response = await chain.ainvoke(payload)
            content = getattr(response, "content", response)
            return validate_generated_sql(parse_sql_generation_output(str(content)))
        except SQLValidationError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error
