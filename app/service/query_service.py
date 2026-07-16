from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import create_initial_state
from app.api.schemas.query_schema import QueryRequest
from app.core.context import request_id_ctx_var
from app.core.events import AgentEvent, elapsed_ms, format_sse
from app.core.exceptions import sanitize_exception
from app.repository.es.value_es_repository import ValueESRepository
from app.repository.mysql.dw_mysql_repository import DWMySQLRepository
from app.repository.mysql.meta_mysql_repository import MetaMySQLRepository
from app.repository.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repository.qdrant.metric_qdrant_repository import MetricQdrantRepository


class QueryService:
    def __init__(
        self,
        embedding_client: HuggingFaceEndpointEmbeddings,
        column_qdrant_repository: ColumnQdrantRepository,
        value_es_repository: ValueESRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        meta_mysql_repository: MetaMySQLRepository,
        dw_mysql_repository: DWMySQLRepository,
    ):
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

    def _context(self) -> DataAgentContext:
        return DataAgentContext(
            embedding_client=self.embedding_client,
            column_qdrant_repository=self.column_qdrant_repository,
            value_es_repository=self.value_es_repository,
            metric_qdrant_repository=self.metric_qdrant_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )

    async def query(self, query_request: QueryRequest, request: Request | None = None) -> AsyncIterator[str]:
        request_id = request_id_ctx_var.get()
        started_at = time.perf_counter()
        sequence = 1

        def emit(
            event: str,
            message: str,
            data: dict[str, Any] | None = None,
            node: str | None = None,
            status: str = "ok",
        ) -> str:
            nonlocal sequence
            payload = AgentEvent(
                request_id=request_id,
                event=event,  # type: ignore[arg-type]
                node=node,
                status=status,
                message=message,
                sequence=sequence,
                elapsed_ms=elapsed_ms(started_at),
                data=data,
            )
            sequence += 1
            return format_sse(payload)

        yield emit("started", "Agent execution started", {"query_length": len(query_request.query)})
        state = create_initial_state(query_request.query)
        if query_request.max_rows is not None:
            state["max_result_rows"] = query_request.max_rows

        try:
            async for chunk in graph.astream(input=state, context=self._context(), stream_mode="custom"):
                if request is not None and await request.is_disconnected():
                    break
                event = chunk.get("event", "stage")
                node = chunk.get("node")
                message = chunk.get("message") or chunk.get("stage") or event
                safe_data = {k: v for k, v in chunk.items() if k not in {"event", "node", "message"}}
                yield emit(event, message, safe_data or None, node=node)
            yield emit("done", "Agent execution finished")
        except Exception as exc:
            app_exc = sanitize_exception(exc)
            yield emit(
                "error",
                app_exc.message,
                {"code": app_exc.code, "details": app_exc.details},
                status="error",
            )
            yield emit("done", "Agent execution finished with error", status="error")
