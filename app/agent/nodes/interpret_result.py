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
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt
from app.security.data_masking import mask_rows


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


async def interpret_result(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "interpret_result", "message": "Interpreting result"})

    summary = state.get("result_summary", {})
    if not state.get("result"):
        interpretation = "\u672a\u67e5\u8be2\u5230\u7b26\u5408\u6761\u4ef6\u7684\u6570\u636e\u3002"
        writer(
            {
                "event": "result",
                "node": "interpret_result",
                "message": "Result interpreted",
                **_final_payload(state, interpretation),
            }
        )
        return {"interpretation": interpretation, "final_answer": interpretation}

    prompt = PromptTemplate(template=load_prompt("interpret_result"), input_variables=["query", "summary"])
    chain = prompt | llm | StrOutputParser()

    chunks: list[str] = []
    async for token in chain.astream(
        {
            "query": state["query"],
            "summary": yaml.dump(summary, allow_unicode=True, sort_keys=False),
        }
    ):
        chunks.append(token)
        writer({"event": "result", "node": "interpret_result", "message": "Interpreting result", "answer_delta": token})

    interpretation = "".join(chunks)
    logger.info(f"result interpreted chars={len(interpretation)}")
    writer(
        {
            "event": "result",
            "node": "interpret_result",
            "message": "Result interpreted",
            **_final_payload(state, interpretation),
        }
    )
    return {"interpretation": interpretation, "final_answer": interpretation}
