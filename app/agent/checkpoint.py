from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.clients.redis_client_manager import redis_client_manager
from app.config.app_config import app_config
from app.core.telemetry import telemetry_manager


class CheckpointStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CheckpointTransitionError(ValueError):
    pass


CHECKPOINT_SAVE_LUA = """
local existing = redis.call('GET', KEYS[1])
if existing then
  local current = cjson.decode(existing)
  local old_status = current['status']
  local new_record = cjson.decode(ARGV[1])
  local new_status = new_record['status']
  if old_status == 'COMPLETED' and new_status ~= 'COMPLETED' then
    return 'invalid'
  end
  if old_status == 'FAILED' and new_status == 'RUNNING' then
    return 'invalid'
  end
  if old_status == 'CANCELLED' and new_status == 'RUNNING' then
    return 'invalid'
  end
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 'ok'
"""

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "connection",
    "password",
    "passwd",
    "prompt",
    "raw",
    "secret",
    "token",
    "traceback",
    "validation_detail",
)

FORBIDDEN_STATE_KEYS = {
    "result",
    "retrieved_values",
    "sql",
    "normalized_sql",
    "validation_detail",
}


@dataclass(frozen=True)
class CheckpointRecord:
    execution_id: str
    request_id: str
    current_node: str
    next_node: str | None
    state_snapshot: dict[str, Any]
    retry_count: int
    budget_state: Mapping[str, Any]
    status: CheckpointStatus
    created_at: float
    updated_at: float
    completed_nodes: dict[str, dict[str, Any]]
    started_emitted: bool = False
    final_emitted: bool = False
    error_emitted: bool = False
    audit_emitted: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CheckpointRecord:
        return cls(
            execution_id=str(payload["execution_id"]),
            request_id=str(payload.get("request_id") or ""),
            current_node=str(payload.get("current_node") or ""),
            next_node=str(payload["next_node"]) if payload.get("next_node") is not None else None,
            state_snapshot=dict(payload.get("state_snapshot") or {}),
            retry_count=int(payload.get("retry_count") or 0),
            budget_state=dict(payload.get("budget_state") or {}),
            status=CheckpointStatus(str(payload.get("status") or CheckpointStatus.RUNNING)),
            created_at=float(payload.get("created_at") or time.time()),
            updated_at=float(payload.get("updated_at") or time.time()),
            completed_nodes=dict(payload.get("completed_nodes") or {}),
            started_emitted=bool(payload.get("started_emitted") or False),
            final_emitted=bool(payload.get("final_emitted") or False),
            error_emitted=bool(payload.get("error_emitted") or False),
            audit_emitted=bool(payload.get("audit_emitted") or False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "request_id": self.request_id,
            "current_node": self.current_node,
            "next_node": self.next_node,
            "state_snapshot": self.state_snapshot,
            "retry_count": self.retry_count,
            "budget_state": self.budget_state,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_nodes": self.completed_nodes,
            "started_emitted": self.started_emitted,
            "final_emitted": self.final_emitted,
            "error_emitted": self.error_emitted,
            "audit_emitted": self.audit_emitted,
        }


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in FORBIDDEN_STATE_KEYS or any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _safe_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[truncated]"
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_safe_json_value(item, depth=depth + 1) for item in list(value)[:100]]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:100]:
            key = str(raw_key)
            if _is_sensitive_key(key):
                continue
            safe[key] = _safe_json_value(raw_value, depth=depth + 1)
        return safe
    return str(value)[:500]


def _has_forbidden_checkpoint_key(state: Mapping[str, Any]) -> bool:
    return any(_is_sensitive_key(str(key)) for key in state)


def sanitize_state_snapshot(state: Mapping[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    sql_text = state.get("normalized_sql") or state.get("sql")
    if isinstance(sql_text, str) and sql_text:
        snapshot["sql_hash"] = _hash_text(sql_text)
    for key, value in state.items():
        if _is_sensitive_key(str(key)):
            continue
        snapshot[str(key)] = _safe_json_value(value)
    return snapshot


class CheckpointManager:
    def __init__(self, *, redis_client: Any, key_prefix: str, ttl_seconds: int):
        self.redis_client = redis_client
        self.key_prefix = key_prefix.rstrip(":")
        self.ttl_seconds = ttl_seconds

    def _client(self) -> Any | None:
        return self.redis_client()

    def key_for(self, execution_id: str) -> str:
        return f"{self.key_prefix}:checkpoint:{execution_id}"

    async def load(self, execution_id: str | None) -> CheckpointRecord | None:
        if not execution_id:
            return None
        client = self._client()
        if client is None:
            return None
        with telemetry_manager.span("redis.checkpoint", {"execution_id": execution_id}):
            raw = await client.get(self.key_for(execution_id))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            return CheckpointRecord.from_dict(payload)
        except (TypeError, ValueError, KeyError):
            return None

    async def resume_state(self, state: Mapping[str, Any], execution_id: str | None) -> dict[str, Any]:
        record = await self.load(execution_id)
        if record is None or record.status != CheckpointStatus.RUNNING:
            return dict(state)
        telemetry_manager.increment_counter("checkpoint_recovery_total", attributes={"execution_id": execution_id})
        resumed = dict(state)
        resumed.update(record.state_snapshot)
        resumed["execution_id"] = record.execution_id
        resumed["request_id"] = record.request_id
        resumed["retry_count"] = record.retry_count
        if record.budget_state:
            resumed["budget"] = record.budget_state
        return resumed

    async def mark_started_emitted(self, execution_id: str, request_id: str, state: Mapping[str, Any]) -> None:
        existing = await self.load(execution_id)
        if existing is not None and existing.status != CheckpointStatus.RUNNING:
            return
        await self._save(
            execution_id=execution_id,
            request_id=request_id,
            current_node="",
            next_node=None,
            state=state,
            status=CheckpointStatus.RUNNING,
            started_emitted=True,
        )

    async def mark_node_running(self, execution_id: str, request_id: str, node: str, state: Mapping[str, Any]) -> None:
        await self._save(
            execution_id=execution_id,
            request_id=request_id,
            current_node=node,
            next_node=node,
            state=state,
            status=CheckpointStatus.RUNNING,
        )

    async def mark_node_completed(
        self,
        execution_id: str,
        request_id: str,
        node: str,
        next_node: str | None,
        state: Mapping[str, Any],
        update: dict[str, Any],
    ) -> None:
        record = await self.load(execution_id)
        completed_nodes = dict(record.completed_nodes) if record is not None else {}
        if not _has_forbidden_checkpoint_key(update):
            completed_nodes[_completion_key(node, int(state.get("retry_count") or 0))] = sanitize_state_snapshot(update)
        await self._save(
            execution_id=execution_id,
            request_id=request_id,
            current_node=node,
            next_node=next_node,
            state=state,
            status=CheckpointStatus.RUNNING,
            completed_nodes=completed_nodes,
        )

    async def mark_completed(self, execution_id: str | None, request_id: str, state: Mapping[str, Any]) -> None:
        if execution_id:
            await self._save(
                execution_id=execution_id,
                request_id=request_id,
                current_node="",
                next_node=None,
                state=state,
                status=CheckpointStatus.COMPLETED,
                final_emitted=True,
                audit_emitted=bool(state.get("audit_logged")),
            )

    async def mark_failed(self, execution_id: str | None, request_id: str, state: Mapping[str, Any]) -> None:
        if execution_id:
            await self._save(
                execution_id=execution_id,
                request_id=request_id,
                current_node=str(state.get("current_node") or ""),
                next_node=None,
                state=state,
                status=CheckpointStatus.FAILED,
                error_emitted=True,
                audit_emitted=bool(state.get("audit_logged")),
            )

    async def mark_cancelled(self, execution_id: str | None, request_id: str, state: Mapping[str, Any]) -> None:
        if execution_id:
            await self._save(
                execution_id=execution_id,
                request_id=request_id,
                current_node=str(state.get("current_node") or ""),
                next_node=None,
                state=state,
                status=CheckpointStatus.CANCELLED,
            )

    async def node_completed(self, execution_id: str | None, node: str, retry_count: int) -> bool:
        record = await self.load(execution_id)
        if record is None or record.status != CheckpointStatus.RUNNING:
            return False
        return _completion_key(node, retry_count) in record.completed_nodes

    async def _save(
        self,
        *,
        execution_id: str,
        request_id: str,
        current_node: str,
        next_node: str | None,
        state: Mapping[str, Any],
        status: CheckpointStatus,
        completed_nodes: dict[str, dict[str, Any]] | None = None,
        started_emitted: bool | None = None,
        final_emitted: bool | None = None,
        error_emitted: bool | None = None,
        audit_emitted: bool | None = None,
    ) -> None:
        client = self._client()
        if client is None:
            return
        existing = await self.load(execution_id)
        now = time.time()
        record = CheckpointRecord(
            execution_id=execution_id,
            request_id=request_id,
            current_node=current_node,
            next_node=next_node,
            state_snapshot=sanitize_state_snapshot(state),
            retry_count=int(state.get("retry_count") or 0),
            budget_state=_safe_json_value(state.get("budget") or {}),
            status=status,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            completed_nodes=completed_nodes
            if completed_nodes is not None
            else (existing.completed_nodes if existing else {}),
            started_emitted=started_emitted
            if started_emitted is not None
            else bool(existing and existing.started_emitted),
            final_emitted=final_emitted if final_emitted is not None else bool(existing and existing.final_emitted),
            error_emitted=error_emitted if error_emitted is not None else bool(existing and existing.error_emitted),
            audit_emitted=audit_emitted if audit_emitted is not None else bool(existing and existing.audit_emitted),
        )
        payload = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
        with telemetry_manager.span("redis.checkpoint", {"execution_id": execution_id}):
            result = await client.eval(CHECKPOINT_SAVE_LUA, 1, self.key_for(execution_id), payload, self.ttl_seconds)
        if str(result) != "ok":
            raise CheckpointTransitionError(f"invalid checkpoint transition for {execution_id}")


def _completion_key(node: str, retry_count: int) -> str:
    return f"{node}:{retry_count}"


checkpoint_manager = CheckpointManager(
    redis_client=lambda: redis_client_manager.client,
    key_prefix=app_config.redis.key_prefix,
    ttl_seconds=app_config.agent.checkpoint_ttl_seconds,
)
