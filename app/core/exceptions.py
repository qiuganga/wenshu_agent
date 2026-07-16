from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.context import request_id_ctx_var


@dataclass
class AppException(Exception):
    code: str
    message: str
    details: Any | None = None
    status_code: int = 400

    def to_response(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "request_id": request_id_ctx_var.get(),
            "details": self.details,
        }


class SQLSecurityError(AppException):
    def __init__(self, message: str = "SQL did not pass readonly security validation", details: Any | None = None):
        super().__init__("SQL_SECURITY_FAILED", message, details, 400)


class SQLValidationError(AppException):
    def __init__(self, message: str = "SQL validation failed", details: Any | None = None):
        super().__init__("SQL_VALIDATION_FAILED", message, details, 400)


class SQLExecutionError(AppException):
    def __init__(self, message: str = "SQL execution failed", details: Any | None = None):
        super().__init__("SQL_EXECUTION_FAILED", message, details, 500)


class RecallError(AppException):
    def __init__(self, message: str = "Knowledge recall failed", details: Any | None = None):
        super().__init__("RECALL_FAILED", message, details, 500)


class AgentRetryExceededError(AppException):
    def __init__(self, message: str = "SQL correction retry limit exceeded", details: Any | None = None):
        super().__init__("AGENT_RETRY_EXCEEDED", message, details, 400)


def sanitize_exception(exc: Exception) -> AppException:
    if isinstance(exc, AppException):
        return exc
    return AppException(
        code="INTERNAL_ERROR",
        message="Agent execution failed. Please retry later or adjust the question.",
        details=None,
        status_code=500,
    )
