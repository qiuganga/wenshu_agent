from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.error_policy import failure_policy
from app.agent.state import DataAgentState
from app.core.exceptions import AgentExecutionFailedError, AgentNonRetryableError, AgentRetryExceededError
from app.core.logging import logger


async def failed(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    policy = failure_policy(
        state.get("error_code"),
        state.get("retryable"),
        validation_detail=state.get("validation_detail"),
    )
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 0)
    retry_exhausted = policy.retryable and retry_count >= max_retries
    logger.warning(
        f"agent failed code={policy.error_code} retries={retry_count} "
        f"retryable={policy.retryable} retry_exhausted={retry_exhausted}"
    )
    writer(
        {
            "event": "error",
            "node": "failed",
            "message": policy.user_message,
            "code": policy.error_code,
            "retryable": policy.retryable,
        }
    )
    details = {"error_code": policy.error_code, "retryable": policy.retryable, "error_already_emitted": True}
    if retry_exhausted:
        raise AgentRetryExceededError(policy.user_message, details)
    if not policy.retryable:
        raise AgentNonRetryableError(policy.user_message, details)
    raise AgentExecutionFailedError(policy.user_message, details)
