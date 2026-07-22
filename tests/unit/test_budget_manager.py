from decimal import Decimal

import pytest

from app.governance.budget import BudgetContext, TokenBudgetManager
from app.governance.common import GovernanceError


def make_context() -> BudgetContext:
    return BudgetContext(
        request_id="request-1",
        execution_id="execution-1",
        user_hash="user-hash",
        tenant_hash="tenant-hash",
        max_input_tokens=100,
        max_output_tokens=100,
        max_total_tokens=150,
        max_cost=Decimal("100"),
        max_agent_steps=2,
        max_llm_calls=2,
        max_handoffs=1,
        max_runtime_seconds=60,
    )


def test_token_budget_reserve_settle_and_release() -> None:
    context = make_context()
    manager = TokenBudgetManager()

    reservation = manager.reserve_llm_call(
        context,
        reservation_id="llm-1",
        estimated_input_tokens=20,
        max_output_tokens=30,
    )
    settled = manager.settle_llm_call(context, reservation, actual_input_tokens=10, actual_output_tokens=15)

    assert settled.settled is True
    assert context.consumed_input_tokens == 10
    assert context.consumed_output_tokens == 15
    manager.release(context, settled)
    assert context.consumed_total_tokens == 25


def test_token_budget_rejects_over_budget_and_limits_steps_handoffs() -> None:
    context = make_context()
    manager = TokenBudgetManager()

    with pytest.raises(GovernanceError, match="Total token budget exceeded"):
        manager.reserve_llm_call(context, reservation_id="too-big", estimated_input_tokens=90, max_output_tokens=90)

    manager.record_agent_step(context)
    manager.record_agent_step(context)
    with pytest.raises(GovernanceError) as step_error:
        manager.record_agent_step(context)
    assert step_error.value.error_code == "AGENT_STEP_LIMIT_EXCEEDED"

    manager.record_handoff(context)
    with pytest.raises(GovernanceError) as handoff_error:
        manager.record_handoff(context)
    assert handoff_error.value.error_code == "HANDOFF_LIMIT_EXCEEDED"


def test_budget_context_safe_snapshot_uses_hashes_only() -> None:
    snapshot = make_context().safe_snapshot()

    assert snapshot["user_hash"] == "user-hash"
    assert snapshot["tenant_hash"] == "tenant-hash"
    assert "user_id" not in snapshot
    assert "tenant_id" not in snapshot
    assert "prompt" not in snapshot
