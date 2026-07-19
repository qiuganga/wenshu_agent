import asyncio
import json
from typing import Any

import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.config.app_config import app_config
from app.core.context import request_id_ctx_var
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt
from app.security.data_masking import mask_rows

FALLBACK_MAX_CHARS = 500
FALLBACK_VALUE_MAX_CHARS = 120
FALLBACK_MAX_COLUMNS = 12


def _payload_within_limit(payload: dict) -> bool:
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    return len(encoded) <= app_config.agent.max_sse_payload_bytes


def _final_payload(state: DataAgentState, interpretation: str) -> dict:
    payload: dict[str, Any] = {
        "final_answer": interpretation,
        "result_summary": state.get("result_summary", {}),
    }
    if app_config.agent.expose_sql_to_client:
        payload["normalized_sql"] = state.get("normalized_sql") or state.get("sql", "")
    if app_config.agent.expose_raw_rows_to_client:
        rows = mask_rows(
            state.get("result", [])[: app_config.agent.result_sample_rows], app_config.security.sensitive_fields
        )
        candidate = {**payload, "rows": rows}
        if _payload_within_limit(candidate):
            payload = candidate
    return payload


def _fallback_final_payload(state: DataAgentState, interpretation: str) -> dict:
    payload: dict[str, Any] = {
        "final_answer": interpretation,
        "result_summary": state.get("result_summary", {}),
    }
    if app_config.agent.expose_sql_to_client:
        payload["normalized_sql"] = state.get("normalized_sql") or state.get("sql", "")
    return payload


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "...[truncated]"
    if max_chars <= len(marker):
        return marker[:max_chars]
    return f"{text[: max_chars - len(marker)]}{marker}"


def _format_columns(columns: Any) -> str:
    if not isinstance(columns, list):
        return "无"
    safe_columns = [str(column) for column in columns[:FALLBACK_MAX_COLUMNS]]
    if len(columns) > FALLBACK_MAX_COLUMNS:
        safe_columns.append("等")
    return "、".join(safe_columns) if safe_columns else "无"


def _format_safe_value(value: Any) -> str:
    if isinstance(value, str):
        return _truncate_text(value, FALLBACK_VALUE_MAX_CHARS)
    return _truncate_text(json.dumps(value, ensure_ascii=False, default=str), FALLBACK_VALUE_MAX_CHARS)


def build_interpretation_fallback(summary: dict[str, Any]) -> str:
    row_count = summary.get("row_count", 0)
    row_count = row_count if isinstance(row_count, int) and row_count >= 0 else 0
    columns = summary.get("columns", [])
    sample = summary.get("sample", [])

    if row_count == 0:
        answer = "查询成功，但没有返回符合条件的数据。"
    elif row_count == 1 and isinstance(columns, list) and len(columns) == 1 and isinstance(sample, list) and sample:
        field = str(columns[0])
        row = sample[0] if isinstance(sample[0], dict) else {}
        answer = f"查询结果：{field} = {_format_safe_value(row.get(field, ''))}。"
    elif row_count == 1:
        answer = f"查询返回 1 行，字段包括：{_format_columns(columns)}。"
    else:
        answer = f"查询成功，共返回 {row_count} 行，字段包括：{_format_columns(columns)}。"

    if summary.get("query_result_truncated") is True:
        answer += "查询结果可能因行数限制而不完整。"
    elif summary.get("sample_truncated") is True:
        answer += "这里只展示了部分样本行。"
    return _truncate_text(answer, FALLBACK_MAX_CHARS)


async def _stream_llm_interpretation(state: DataAgentState, summary: dict[str, Any]):
    prompt = PromptTemplate(template=load_prompt("interpret_result"), input_variables=["query", "summary"])
    chain = prompt | llm | StrOutputParser()
    async for token in chain.astream(
        {
            "query": state["query"],
            "summary": yaml.dump(summary, allow_unicode=True, sort_keys=False),
        }
    ):
        yield token


async def interpret_result(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "interpret_result", "message": "Interpreting result"})

    summary = state.get("result_summary", {})
    if summary.get("row_count") == 0:
        interpretation = build_interpretation_fallback(summary)
        writer(
            {
                "event": "result",
                "node": "interpret_result",
                "message": "Result interpreted",
                **_fallback_final_payload(state, interpretation),
            }
        )
        return {"interpretation": interpretation, "final_answer": interpretation}

    chunks: list[str] = []
    token_buffer: list[str] = []

    def flush_token_buffer() -> None:
        if not token_buffer:
            return
        delta = "".join(token_buffer)
        token_buffer.clear()
        writer({"event": "result", "node": "interpret_result", "message": "Interpreting result", "answer_delta": delta})

    fallback_used = False
    try:
        async for token in _stream_llm_interpretation(state, summary):
            chunks.append(token)
            token_buffer.append(token)
            if sum(len(part) for part in token_buffer) >= app_config.agent.token_batch_chars:
                flush_token_buffer()
        flush_token_buffer()
        interpretation = "".join(chunks)
        if not interpretation.strip():
            fallback_used = True
            interpretation = build_interpretation_fallback(summary)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        token_buffer.clear()
        fallback_used = True
        logger.warning(
            f"interpret_result fallback request_id={request_id_ctx_var.get()} "
            f"node=interpret_result exception_type={type(exc).__name__} fallback=True"
        )
        interpretation = build_interpretation_fallback(summary)

    logger.info(f"result interpreted chars={len(interpretation)} fallback={fallback_used}")
    payload_builder = _fallback_final_payload if fallback_used else _final_payload
    writer(
        {
            "event": "result",
            "node": "interpret_result",
            "message": "Result interpreted",
            **payload_builder(state, interpretation),
        }
    )
    return {"interpretation": interpretation, "final_answer": interpretation}
