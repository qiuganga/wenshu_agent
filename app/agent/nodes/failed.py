from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.exceptions import AgentRetryExceededError
from app.core.logging import logger


async def failed(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    error_code = state.get("error_code") or "AGENT_FAILED"
    message = "Agent failed before SQL execution"
    logger.warning(f"agent failed code={error_code} retries={state.get('retry_count', 0)} error={state.get('error')}")
    writer({"event": "error", "node": "failed", "message": message, "code": error_code})
    raise AgentRetryExceededError(message, {"error_code": error_code})
