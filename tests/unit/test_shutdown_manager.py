import asyncio

import pytest

from app.core.shutdown import ShutdownManager
from app.core.telemetry import telemetry_manager


@pytest.mark.asyncio
async def test_shutdown_manager_runs_stop_accepting_and_cleanup():
    calls = []
    manager = ShutdownManager(timeout_seconds=1)
    telemetry_manager.enable_test_capture()

    async def stop_accepting():
        calls.append("stop")

    async def cleanup():
        calls.append("cleanup")

    try:
        result = await manager.run(stop_accepting=stop_accepting, cleanup_steps=[cleanup])
    finally:
        telemetry_manager.disable_test_capture()

    assert result.graceful is True
    assert result.timed_out is False
    assert calls == ["stop", "cleanup"]


@pytest.mark.asyncio
async def test_shutdown_manager_forces_timeout():
    manager = ShutdownManager(timeout_seconds=0.01)

    async def stop_accepting():
        return None

    async def slow_cleanup():
        await asyncio.sleep(1)

    result = await manager.run(stop_accepting=stop_accepting, cleanup_steps=[slow_cleanup])

    assert result.graceful is False
    assert result.timed_out is True
