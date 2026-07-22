from __future__ import annotations

import json

import pytest

from app.agent.checkpoint import (
    CHECKPOINT_SAVE_LUA,
    CheckpointManager,
    CheckpointStatus,
    CheckpointTransitionError,
)


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def eval(self, script: str, numkeys: int, *args):
        assert script == CHECKPOINT_SAVE_LUA
        key = args[0]
        payload = str(args[1])
        ttl = int(args[2])
        existing = self.values.get(key)
        if existing is not None:
            old_status = json.loads(existing)["status"]
            new_status = json.loads(payload)["status"]
            if old_status == "COMPLETED" and new_status != "COMPLETED":
                return "invalid"
            if old_status in {"FAILED", "CANCELLED"} and new_status == "RUNNING":
                return "invalid"
        self.values[key] = payload
        self.ttls[key] = ttl
        return "ok"


def manager_for(redis: FakeRedis) -> CheckpointManager:
    return CheckpointManager(redis_client=lambda: redis, key_prefix="agent", ttl_seconds=60)


@pytest.mark.asyncio
async def test_checkpoint_save_load_and_update():
    redis = FakeRedis()
    manager = manager_for(redis)

    await manager.mark_node_running("exec-1", "req-1", "node_a", {"retry_count": 0, "budget": {"remaining": 10}})
    record = await manager.load("exec-1")

    assert record is not None
    assert record.execution_id == "exec-1"
    assert record.request_id == "req-1"
    assert record.current_node == "node_a"
    assert record.status == CheckpointStatus.RUNNING
    assert record.budget_state == {"remaining": 10}
    assert redis.ttls[manager.key_for("exec-1")] == 60

    await manager.mark_node_completed(
        "exec-1",
        "req-1",
        "node_a",
        "node_b",
        {"retry_count": 0, "keywords": ["x"]},
        {"keywords": ["x"]},
    )
    updated = await manager.load("exec-1")

    assert updated is not None
    assert updated.current_node == "node_a"
    assert updated.next_node == "node_b"
    assert updated.state_snapshot["keywords"] == ["x"]
    assert await manager.node_completed("exec-1", "node_a", 0) is True


@pytest.mark.asyncio
async def test_checkpoint_write_is_idempotent_for_same_execution_id():
    redis = FakeRedis()
    manager = manager_for(redis)

    await manager.mark_node_running("exec-1", "req-1", "node_a", {"retry_count": 0})
    await manager.mark_node_running("exec-1", "req-1", "node_a", {"retry_count": 0})

    assert list(redis.values) == [manager.key_for("exec-1")]
    record = await manager.load("exec-1")
    assert record is not None
    assert record.status == CheckpointStatus.RUNNING


@pytest.mark.asyncio
async def test_checkpoint_rejects_invalid_status_transition():
    redis = FakeRedis()
    manager = manager_for(redis)

    await manager.mark_completed("exec-1", "req-1", {"retry_count": 0})

    with pytest.raises(CheckpointTransitionError):
        await manager.mark_node_running("exec-1", "req-1", "node_a", {"retry_count": 0})


@pytest.mark.asyncio
async def test_checkpoint_serialization_safety_excludes_sensitive_values():
    redis = FakeRedis()
    manager = manager_for(redis)
    state = {
        "retry_count": 0,
        "sql": "select * from orders",
        "normalized_sql": "select * from orders",
        "result": [{"password": "secret"}],
        "validation_detail": "host: db.internal password: secret",
        "api_key": "sk-secret",
        "result_summary": {"row_count": 1},
    }

    await manager.mark_node_completed("exec-1", "req-1", "node_a", "node_b", state, state)
    raw = redis.values[manager.key_for("exec-1")]
    record = json.loads(raw)

    assert "select * from orders" not in raw
    assert "secret" not in raw
    assert "db.internal" not in raw
    assert "sql_hash" in record["state_snapshot"]
    assert record["state_snapshot"]["result_summary"] == {"row_count": 1}


@pytest.mark.asyncio
async def test_mark_started_ignores_terminal_checkpoint():
    redis = FakeRedis()
    manager = manager_for(redis)

    await manager.mark_completed("exec-1", "req-1", {"retry_count": 0})
    await manager.mark_started_emitted("exec-1", "req-1", {"retry_count": 0})
    record = await manager.load("exec-1")

    assert record is not None
    assert record.status == CheckpointStatus.COMPLETED


@pytest.mark.asyncio
async def test_sensitive_node_output_is_not_marked_completed():
    redis = FakeRedis()
    manager = manager_for(redis)

    await manager.mark_node_completed(
        "exec-1",
        "req-1",
        "generate_sql",
        "security_validate_sql",
        {"retry_count": 0, "sql": "select * from orders"},
        {"sql": "select * from orders"},
    )

    assert await manager.node_completed("exec-1", "generate_sql", 0) is False
    raw = redis.values[manager.key_for("exec-1")]
    assert "select * from orders" not in raw
