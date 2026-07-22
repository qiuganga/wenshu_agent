from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.checkpoint import CheckpointStatus, checkpoint_manager
from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState, create_initial_state
from app.api.schemas.query_schema import QueryRequest
from app.cache.models import CacheIdentity
from app.cache.service import QueryCacheService, query_cache_service
from app.clients.redis_client_manager import redis_client_manager
from app.config.app_config import app_config
from app.core.context import execution_id_ctx_var, request_id_ctx_var
from app.core.events import AgentEvent, elapsed_ms, format_sse
from app.core.exceptions import AppException, sanitize_exception
from app.core.query_audit import log_query_audit
from app.core.telemetry import telemetry_manager
from app.repository.es.value_es_repository import ValueESRepository
from app.repository.mysql.dw_mysql_repository import DWMySQLRepository
from app.repository.mysql.meta_mysql_repository import MetaMySQLRepository
from app.repository.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repository.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.service.query_lifecycle import (
    AdmissionLease,
    LifecycleSSEQueue,
    QueryExecutionBudget,
    QueryLifecycleError,
    RedisQueryAdmissionController,
    RedisRequestDedupRegistry,
)

_DONE = object()

admission_controller = RedisQueryAdmissionController(
    max_global=app_config.agent.max_concurrent_queries,
    max_per_user=app_config.agent.max_concurrent_queries_per_user,
    timeout_seconds=app_config.agent.admission_timeout_seconds,
    redis_client=lambda: redis_client_manager.client,
    key_prefix=app_config.redis.key_prefix,
    lease_ttl_seconds=app_config.agent.query_total_timeout_seconds + app_config.agent.admission_timeout_seconds,
)
request_dedup_registry = RedisRequestDedupRegistry(
    ttl_seconds=app_config.agent.request_dedup_ttl_seconds,
    max_entries=app_config.agent.request_dedup_max_entries,
    redis_client=lambda: redis_client_manager.client,
    key_prefix=app_config.redis.key_prefix,
)


def _error_already_emitted(details: Any | None) -> bool:
    return isinstance(details, dict) and details.get("error_already_emitted") is True


async def watch_disconnect(request: Request, interval_seconds: float = 0.2) -> None:
    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(interval_seconds)


class QueryService:
    def __init__(
        self,
        embedding_client: HuggingFaceEndpointEmbeddings,
        column_qdrant_repository: ColumnQdrantRepository,
        value_es_repository: ValueESRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        meta_mysql_repository: MetaMySQLRepository,
        dw_mysql_repository: DWMySQLRepository,
        agent_graph: Any | None = None,
        cache_service: QueryCacheService | None = None,
    ):
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.agent_graph: Any = agent_graph or graph
        self.cache_service = cache_service or query_cache_service

    def _context(self) -> DataAgentContext:
        return DataAgentContext(
            embedding_client=self.embedding_client,
            column_qdrant_repository=self.column_qdrant_repository,
            value_es_repository=self.value_es_repository,
            metric_qdrant_repository=self.metric_qdrant_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )

    async def _produce_graph_chunks(self, stream: LifecycleSSEQueue, state: DataAgentState) -> None:
        agen = self.agent_graph.astream(input=state, context=self._context(), stream_mode="custom")
        try:
            with telemetry_manager.span(
                "graph_execution",
                {
                    "execution_id": state.get("execution_id"),
                    "retry_count": state.get("retry_count", 0),
                },
            ):
                async for chunk in agen:
                    await stream.put_graph_event(chunk)
            await asyncio.wait_for(stream.queue.put(_DONE), timeout=app_config.agent.sse_put_timeout_seconds)
        except asyncio.CancelledError as exc:
            await stream.put_exception(exc)
            with contextlib.suppress(Exception):
                await agen.aclose()
            raise
        except Exception as exc:
            await stream.put_exception(exc)
        finally:
            with contextlib.suppress(Exception):
                await agen.aclose()

    async def query(self, query_request: QueryRequest, request: Request | None = None) -> AsyncIterator[str]:
        request_id = request_id_ctx_var.get()
        budget = QueryExecutionBudget(total_timeout_seconds=app_config.agent.query_total_timeout_seconds)
        started_at = budget.started_at
        sequence = 1
        user_id = query_request.user_id or query_request.conversation_id or "anonymous"
        fallback_request_key = f"local:{id(query_request)}"
        dedup_request_id = query_request.request_id or (request_id if request_id != "-" else None)
        execution_id = query_request.execution_id or ""
        execution_id_ctx_var.set(execution_id or "-")
        existing_checkpoint = await checkpoint_manager.load(execution_id)
        is_resume = existing_checkpoint is not None and existing_checkpoint.status == CheckpointStatus.RUNNING
        admission_lease: AdmissionLease | None = None
        dedup_token = None
        stream: LifecycleSSEQueue | None = None
        graph_task: asyncio.Task[Any] | None = None
        disconnect_task: asyncio.Task[Any] | None = None
        cache_identity: CacheIdentity | None = None
        cache_lease_owner: str | None = None
        cache_final_payload: dict[str, Any] | None = None
        final_status = "failed"
        client_disconnected = False
        query_started_at = time.perf_counter()
        telemetry_manager.increment_counter("query_total")
        query_span = telemetry_manager.span(
            "query_execution",
            {
                "execution_id": execution_id,
                "request_id": dedup_request_id or request_id,
            },
        )
        query_span.__enter__()

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

        if not is_resume:
            yield emit("started", "Agent execution started", {"query_length": len(query_request.query)})
            if execution_id:
                await checkpoint_manager.mark_started_emitted(
                    execution_id,
                    dedup_request_id or request_id,
                    {
                        "query": query_request.query,
                        "execution_id": execution_id,
                        "request_id": dedup_request_id or request_id,
                    },
                )
        try:
            if dedup_request_id is not None:
                with telemetry_manager.span("redis.dedup", {"execution_id": execution_id}):
                    dedup_token = await request_dedup_registry.register(dedup_request_id)
            admission_key = dedup_token.request_id_hash if dedup_token is not None else fallback_request_key
            with telemetry_manager.span("redis.admission", {"execution_id": execution_id}):
                admission_lease = await admission_controller.acquire(user_id=user_id, key=admission_key)
        except AppException as exc:
            app_exc = sanitize_exception(exc)
            details = app_exc.details if isinstance(app_exc.details, dict) else {}
            final_status = "duplicate" if app_exc.code == "DUPLICATE_REQUEST" else "rejected"
            telemetry_manager.increment_counter("admission_reject_total", attributes={"error_code": app_exc.code})
            self._audit_terminal(
                app_exc.code,
                final_status=final_status,
                retry_count=0,
                admission_wait_ms=0,
                global_active_queries=details.get("global_active_queries"),
                user_active_queries=details.get("user_active_queries"),
                duplicate_request=app_exc.code == "DUPLICATE_REQUEST",
            )
            yield emit(
                "error",
                app_exc.message,
                {"code": app_exc.code, "details": app_exc.details},
                status="error",
            )
            yield emit("done", "Agent execution finished with error", status="error")
            if dedup_token is not None:
                await request_dedup_registry.complete(dedup_token, "failed")
            error_code_for_metrics = (
                (app_exc.details or {}).get("error_code") if isinstance(app_exc.details, dict) else app_exc.code
            )
            telemetry_manager.increment_counter("query_failed_total", attributes={"error_code": error_code_for_metrics})
            if app_exc.code == "QUERY_TOTAL_TIMEOUT" or error_code_for_metrics == "QUERY_TOTAL_TIMEOUT":
                telemetry_manager.increment_counter(
                    "query_timeout_total", attributes={"error_code": "QUERY_TOTAL_TIMEOUT"}
                )
            telemetry_manager.record_histogram("query_latency_seconds", time.perf_counter() - query_started_at)
            query_span.__exit__(None, None, None)
            return

        snapshot = admission_controller.snapshot_for(user_id, admission_lease.wait_ms)
        telemetry_manager.set_active_queries(snapshot.global_active_queries)
        cache_identity = self.cache_service.build_identity(query=query_request.query, user_id=user_id)
        cache_lookup = await self.cache_service.lookup(cache_identity)
        if cache_lookup.result.hit and cache_lookup.payload is not None:
            yield emit("result", "Cache hit", cache_lookup.payload, node="cache")
            yield emit("done", "Agent execution finished")
            await request_dedup_registry.complete(dedup_token, "completed")
            telemetry_manager.increment_counter("query_success_total")
            telemetry_manager.record_histogram("query_latency_seconds", time.perf_counter() - query_started_at)
            self._audit_terminal(
                None,
                final_status="success",
                retry_count=0,
                admission_wait_ms=snapshot.admission_wait_ms,
                global_active_queries=snapshot.global_active_queries,
                user_active_queries=snapshot.user_active_queries,
                cache_hit=True,
                cache_type=cache_lookup.result.cache_type,
            )
            final_status = "success"
            return

        cache_lease_owner = await self.cache_service.acquire_lease(cache_identity)
        if cache_lease_owner is None:
            filled_lookup = await self.cache_service.wait_for_fill(cache_identity)
            if filled_lookup is not None and filled_lookup.result.hit and filled_lookup.payload is not None:
                yield emit("result", "Cache hit", filled_lookup.payload, node="cache")
                yield emit("done", "Agent execution finished")
                await request_dedup_registry.complete(dedup_token, "completed")
                telemetry_manager.increment_counter("query_success_total")
                telemetry_manager.record_histogram("query_latency_seconds", time.perf_counter() - query_started_at)
                self._audit_terminal(
                    None,
                    final_status="success",
                    retry_count=0,
                    admission_wait_ms=snapshot.admission_wait_ms,
                    global_active_queries=snapshot.global_active_queries,
                    user_active_queries=snapshot.user_active_queries,
                    cache_hit=True,
                    cache_type=filled_lookup.result.cache_type,
                )
                final_status = "success"
                return

        state = create_initial_state(query_request.query)
        state["execution_id"] = execution_id
        state["request_id"] = dedup_request_id or request_id
        state["budget"] = budget.summary()
        state["admission_wait_ms"] = snapshot.admission_wait_ms
        state["global_active_queries"] = snapshot.global_active_queries
        state["user_active_queries"] = snapshot.user_active_queries
        if query_request.max_rows is not None:
            state["max_result_rows"] = min(query_request.max_rows, app_config.agent.max_result_rows)
        state = await checkpoint_manager.resume_state(state, execution_id)  # type: ignore[assignment]

        stream = LifecycleSSEQueue(
            maxsize=app_config.agent.sse_queue_maxsize,
            put_timeout_seconds=app_config.agent.sse_put_timeout_seconds,
        )
        graph_task = asyncio.create_task(self._produce_graph_chunks(stream, state))
        admission_controller.register_task(graph_task)
        disconnect_task = (
            asyncio.create_task(watch_disconnect(request, app_config.agent.disconnect_poll_interval_seconds))
            if request is not None
            else None
        )
        try:
            while True:
                remaining_budget = budget.remaining_or_raise()
                queue_task = asyncio.create_task(stream.queue.get())
                wait_set = {queue_task}
                if disconnect_task is not None:
                    wait_set.add(disconnect_task)
                done, pending = await asyncio.wait(
                    wait_set,
                    timeout=remaining_budget,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    queue_task.cancel()
                    raise QueryLifecycleError(
                        "QUERY_TOTAL_TIMEOUT",
                        "Query total timeout",
                        {"error_code": "QUERY_TOTAL_TIMEOUT", "retryable": False, "budget_exhausted": True},
                        status_code=504,
                    )
                if queue_task in pending:
                    queue_task.cancel()

                if disconnect_task is not None and disconnect_task in done:
                    client_disconnected = True
                    stream.closed = True
                    graph_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await graph_task
                    await request_dedup_registry.complete(dedup_token, "cancelled")
                    telemetry_manager.increment_counter(
                        "query_failed_total",
                        attributes={"error_code": "CLIENT_DISCONNECTED"},
                    )
                    await checkpoint_manager.mark_cancelled(execution_id, dedup_request_id or request_id, state)
                    final_status = "cancelled"
                    return

                item = await queue_task
                if item is _DONE:
                    await checkpoint_manager.mark_completed(execution_id, dedup_request_id or request_id, state)
                    if cache_identity is not None and cache_final_payload is not None:
                        await self.cache_service.write(
                            identity=cache_identity,
                            payload=cache_final_payload,
                            final_status="success",
                            metadata={
                                "read_only": True,
                                "data_version": cache_identity.scope.data_version,
                                "checkpoint_resumed": is_resume,
                                "fallback_used": False,
                            },
                        )
                    yield emit("done", "Agent execution finished")
                    await request_dedup_registry.complete(dedup_token, "completed")
                    telemetry_manager.increment_counter("query_success_total")
                    telemetry_manager.record_histogram("query_latency_seconds", time.perf_counter() - query_started_at)
                    final_status = "success"
                    return
                if isinstance(item, BaseException):
                    raise item

                chunk = item
                event = chunk.get("event", "stage")
                node = chunk.get("node")
                message = chunk.get("message") or chunk.get("stage") or event
                safe_data = {k: v for k, v in chunk.items() if k not in {"event", "node", "message"}}
                if event == "result" and "final_answer" in safe_data:
                    cache_final_payload = dict(safe_data)
                yield emit(event, message, safe_data or None, node=node)
        except asyncio.CancelledError:
            if stream is not None:
                stream.closed = True
            if graph_task is not None:
                graph_task.cancel()
            await request_dedup_registry.complete(dedup_token, "cancelled")
            checkpoint_state = state if "state" in locals() else {}
            await checkpoint_manager.mark_cancelled(execution_id, dedup_request_id or request_id, checkpoint_state)
            raise
        except Exception as exc:
            app_exc = sanitize_exception(exc)
            final_status = "failed"
            if not _error_already_emitted(app_exc.details):
                yield emit(
                    "error",
                    app_exc.message,
                    {"code": app_exc.code, "details": app_exc.details},
                    status="error",
                )
            yield emit("done", "Agent execution finished with error", status="error")
            await request_dedup_registry.complete(dedup_token, "failed")
            await checkpoint_manager.mark_failed(
                execution_id, dedup_request_id or request_id, state if "state" in locals() else {}
            )
            details = app_exc.details if isinstance(app_exc.details, dict) else {}
            error_code_for_metrics = details.get("error_code") or app_exc.code
            telemetry_manager.increment_counter(
                "query_failed_total",
                attributes={"error_code": error_code_for_metrics},
            )
            if error_code_for_metrics == "QUERY_TOTAL_TIMEOUT":
                telemetry_manager.increment_counter(
                    "query_timeout_total",
                    attributes={"error_code": "QUERY_TOTAL_TIMEOUT"},
                )
            telemetry_manager.record_histogram("query_latency_seconds", time.perf_counter() - query_started_at)
            self._audit_terminal(
                details.get("error_code") or app_exc.code,
                final_status=final_status,
                retry_count=0,
                admission_wait_ms=admission_lease.wait_ms if admission_lease else None,
                global_active_queries=snapshot.global_active_queries,
                user_active_queries=snapshot.user_active_queries,
                budget_exhausted=details.get("budget_exhausted") is True or app_exc.code == "QUERY_TOTAL_TIMEOUT",
                dropped_sse_events=stream.dropped_events if stream else None,
                client_disconnected=client_disconnected,
            )
        finally:
            if stream is not None:
                stream.closed = True
            if graph_task is not None:
                graph_task.cancel()
            if disconnect_task is not None:
                disconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, AttributeError):
                await graph_task
            if disconnect_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await disconnect_task
            if cache_identity is not None:
                await self.cache_service.release_lease(cache_identity, cache_lease_owner)
            await admission_controller.release(admission_lease)
            telemetry_manager.set_active_queries(0)
            query_span.__exit__(None, None, None)

    def _audit_terminal(
        self,
        error_code: str | None,
        *,
        final_status: str,
        retry_count: int,
        admission_wait_ms: int | None = None,
        global_active_queries: int | None = None,
        user_active_queries: int | None = None,
        budget_exhausted: bool | None = None,
        dropped_sse_events: int | None = None,
        duplicate_request: bool | None = None,
        client_disconnected: bool | None = None,
        cache_hit: bool | None = None,
        cache_type: str | None = None,
    ) -> None:
        log_query_audit(
            normalized_sql="",
            referenced_tables=[],
            sql_cost={},
            execution_time_ms=None,
            result_row_count=None,
            result_truncated=None,
            retry_count=retry_count,
            final_status=final_status,
            error_code=error_code,
            admission_wait_ms=admission_wait_ms,
            global_active_queries=global_active_queries,
            user_active_queries=user_active_queries,
            budget_exhausted=budget_exhausted,
            dropped_sse_events=dropped_sse_events,
            duplicate_request=duplicate_request,
            client_disconnected=client_disconnected,
            cache_hit=cache_hit,
            cache_type=cache_type,
        )
