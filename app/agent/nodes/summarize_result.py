from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.nodes._result_summary import summarize_result as build_result_summary
from app.agent.state import DataAgentState
from app.core.logging import logger


async def summarize_result(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "summarize_result", "message": "Summarizing result"})

    summary = build_result_summary(state.get("result", []))
    logger.info(f"result summarized rows={summary['row_count']} columns={len(summary['columns'])}")
    return {"result_summary": summary}
