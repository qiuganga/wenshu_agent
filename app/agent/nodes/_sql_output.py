from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import ValidationError
from sqlglot import parse
from sqlglot.errors import ParseError

from app.config.app_config import app_config
from app.core.exceptions import SQLValidationError
from app.core.logging import logger
from app.security.sql_security import SQLGenerationResult

SQL_OUTPUT_PARSER = PydanticOutputParser(pydantic_object=SQLGenerationResult)


def sql_format_instructions() -> str:
    return SQL_OUTPUT_PARSER.get_format_instructions()


def _strip_code_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def _extract_json(text: str) -> dict[str, Any]:
    clean = _strip_code_fence(text)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise SQLValidationError("LLM SQL output is not valid JSON", {"code": "LLM_SQL_PARSE_FAILED"}) from exc
    if not isinstance(value, dict):
        raise SQLValidationError("LLM SQL output must be a JSON object", {"code": "LLM_SQL_SCHEMA_FAILED"})
    return value


def parse_sql_generation_output(text: str) -> SQLGenerationResult:
    try:
        return SQL_OUTPUT_PARSER.parse(text)
    except Exception:
        try:
            return SQLGenerationResult.model_validate(_extract_json(text))
        except ValidationError as exc:
            raise SQLValidationError(
                "LLM SQL output schema validation failed", {"code": "LLM_SQL_SCHEMA_FAILED"}
            ) from exc
        except SQLValidationError:
            raise


def validate_generated_sql(value: SQLGenerationResult, dialect: str = "mysql") -> str:
    sql = _strip_code_fence(value.sql)
    if not sql:
        raise SQLValidationError("LLM generated empty SQL", {"code": "LLM_SQL_EMPTY"})
    try:
        expressions = [expr for expr in parse(sql, read=dialect) if expr is not None]
    except ParseError as exc:
        raise SQLValidationError("LLM generated SQL cannot be parsed", {"code": "LLM_SQL_NOT_PURE"}) from exc
    if len(expressions) != 1:
        raise SQLValidationError("LLM generated multiple SQL statements", {"code": "LLM_SQL_NOT_PURE"})
    return sql


def _error_code(exc: Exception) -> str:
    details = getattr(exc, "details", None)
    if isinstance(details, dict) and isinstance(details.get("code"), str):
        return details["code"]
    return getattr(exc, "code", "LLM_SQL_PARSE_FAILED")


async def _invoke_structured(llm: Any, payload: dict[str, Any]) -> SQLGenerationResult | None:
    if not hasattr(llm, "with_structured_output"):
        return None
    try:
        structured_llm = llm.with_structured_output(SQLGenerationResult)
        result = await structured_llm.ainvoke(payload)
        if isinstance(result, SQLGenerationResult):
            return result
        return SQLGenerationResult.model_validate(result)
    except NotImplementedError:
        return None
    except Exception as exc:
        raise SQLValidationError("Structured LLM SQL output failed", {"code": "LLM_SQL_SCHEMA_FAILED"}) from exc


async def invoke_sql_chain(prompt: PromptTemplate, llm: Any, payload: dict[str, Any], dialect: str = "mysql") -> str:
    attempts = app_config.agent.llm_output_parse_retries + 1
    last_error: Exception | None = None
    current_payload = dict(payload)

    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        previous_output = ""
        try:
            structured_result = await _invoke_structured(llm, current_payload)
            if structured_result is not None:
                sql = validate_generated_sql(structured_result, dialect=dialect)
                logger.info(
                    f"llm sql structured output success model={app_config.llm.model_name} attempt={attempt} "
                    f"latency_ms={int((time.perf_counter() - started) * 1000)}"
                )
                return sql

            if hasattr(llm, "ainvoke") and not hasattr(llm, "InputType"):
                response = await llm.ainvoke(current_payload)
            else:
                chain = prompt | llm
                response = await chain.ainvoke(current_payload)
            content = str(getattr(response, "content", response))
            previous_output = content[:500]
            sql = validate_generated_sql(parse_sql_generation_output(content), dialect=dialect)
            logger.info(
                f"llm sql fallback output success model={app_config.llm.model_name} attempt={attempt} "
                f"response_length={len(content)} latency_ms={int((time.perf_counter() - started) * 1000)}"
            )
            return sql
        except SQLValidationError as exc:
            last_error = exc
            code = _error_code(exc)
            logger.warning(
                f"llm sql output parse failed model={app_config.llm.model_name} attempt={attempt} "
                f"error_code={code} response_length={len(previous_output)}"
            )
            current_payload = {
                **payload,
                "previous_output": previous_output,
                "parse_error": code,
                "correction_instruction": 'Return only JSON matching the required schema: {"sql": "..."}.',
            }

    raise SQLValidationError(
        "LLM SQL output retries exceeded",
        {"code": "LLM_SQL_RETRIES_EXCEEDED", "last_error": _error_code(last_error) if last_error else None},
    )
