from contextvars import ContextVar

request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="-")
trace_id_ctx_var: ContextVar[str] = ContextVar("trace_id", default="-")
execution_id_ctx_var: ContextVar[str] = ContextVar("execution_id", default="-")
