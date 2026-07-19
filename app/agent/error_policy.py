from __future__ import annotations

import asyncio
from dataclasses import dataclass

RETRYABLE_ERROR_CODES = frozenset(
    {
        "SQL_SECURITY_FAILED",
        "SQL_SECURITY_VALIDATION_FAILED",
        "SQL_VALIDATION_FAILED",
        "SQL_COST_TOO_HIGH",
        "LLM_SQL_PARSE_FAILED",
        "LLM_SQL_SCHEMA_FAILED",
        "LLM_SQL_EMPTY",
        "LLM_SQL_NOT_PURE",
        "LLM_SQL_RETRIES_EXCEEDED",
    }
)

NON_RETRYABLE_ERROR_CODES = frozenset(
    {
        "AGENT_FAILED",
        "DATABASE_UNAVAILABLE",
        "DB_CONNECTION_FAILED",
        "INTERNAL_ERROR",
        "LLM_UNAVAILABLE",
        "PERMISSION_DENIED",
        "SQL_COST_ASSESSMENT_FAILED",
        "SQL_EXECUTION_FAILED",
    }
)

SQL_FIXABLE_DETAIL_SIGNALS = (
    "unknown column",
    "unknown table",
    "doesn't exist",
    "ambiguous column",
    "syntax error",
    "parse error",
)


SAFE_ERROR_MESSAGES = {
    "SQL_COST_TOO_HIGH": "查询范围过大或执行成本过高，请缩小时间范围、减少维度或简化查询条件。",
    "SQL_SECURITY_FAILED": "当前查询未通过安全检查，请调整查询内容后重试。",
    "SQL_SECURITY_VALIDATION_FAILED": "当前查询未通过安全检查，请调整查询内容后重试。",
    "SQL_VALIDATION_FAILED": "未能生成可执行的查询，请换一种方式描述问题。",
    "DATABASE_UNAVAILABLE": "数据服务暂时不可用，请稍后重试。",
    "DB_CONNECTION_FAILED": "数据服务暂时不可用，请稍后重试。",
    "PERMISSION_DENIED": "当前请求无法访问所需数据。",
    "LLM_UNAVAILABLE": "智能分析服务暂时不可用，请稍后重试。",
}
DEFAULT_SAFE_ERROR_MESSAGE = "本次查询未能完成，请稍后重试或调整问题描述。"


@dataclass(frozen=True)
class FailurePolicy:
    error_code: str
    retryable: bool
    user_message: str


def classify_retryable_error(
    error_code: str | None = None,
    validation_detail: str | None = None,
    exception: BaseException | None = None,
) -> bool:
    if isinstance(exception, asyncio.CancelledError):
        raise exception

    if error_code in RETRYABLE_ERROR_CODES:
        return True
    if error_code in NON_RETRYABLE_ERROR_CODES:
        return False

    detail = (validation_detail or "").lower()
    if error_code == "SQL_VALIDATION_FAILED" and any(signal in detail for signal in SQL_FIXABLE_DETAIL_SIGNALS):
        return True
    return False


def safe_error_message(error_code: str | None) -> str:
    if not error_code:
        return DEFAULT_SAFE_ERROR_MESSAGE
    return SAFE_ERROR_MESSAGES.get(error_code, DEFAULT_SAFE_ERROR_MESSAGE)


def failure_policy(
    error_code: str | None,
    retryable: bool | None,
    validation_detail: str | None = None,
) -> FailurePolicy:
    stable_code = error_code or "AGENT_FAILED"
    effective_retryable = retryable
    if effective_retryable is None:
        effective_retryable = classify_retryable_error(stable_code, validation_detail=validation_detail)
    return FailurePolicy(
        error_code=stable_code,
        retryable=effective_retryable,
        user_message=safe_error_message(stable_code),
    )
