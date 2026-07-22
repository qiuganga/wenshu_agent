from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.governance.budget import BudgetContext
from app.governance.common import GovernanceError
from app.governance.cost_budget import CostBudgetManager
from app.governance.pricing import PricingCatalog, PricingEntry


def make_context() -> BudgetContext:
    return BudgetContext(
        request_id="request-1",
        execution_id="execution-1",
        user_hash="user-hash",
        tenant_hash="tenant-hash",
        max_input_tokens=1000,
        max_output_tokens=1000,
        max_total_tokens=1000,
        max_cost=Decimal("10"),
        max_agent_steps=10,
        max_llm_calls=10,
        max_handoffs=10,
        max_runtime_seconds=60,
    )


def test_pricing_catalog_uses_decimal_minor_units_and_version() -> None:
    catalog = PricingCatalog(
        [
            PricingEntry(
                provider="test",
                model_name="m1",
                pricing_version="v1",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                input_price_per_million_tokens=Decimal("2.00"),
                output_price_per_million_tokens=Decimal("4.00"),
                currency="USD",
                source="test",
            )
        ]
    )

    cost = catalog.price_usage(model_name="m1", input_tokens=1_000_000, output_tokens=500_000, usage_source="provider")

    assert cost.total_minor_units == 400
    assert cost.pricing_version == "v1"
    assert cost.usage_source == "provider"


def test_unknown_pricing_fails_safe_or_marks_unknown() -> None:
    with pytest.raises(GovernanceError):
        PricingCatalog(strict_unknown_pricing=True).price_usage(
            model_name="missing",
            input_tokens=1,
            output_tokens=1,
            usage_source="estimated",
        )

    cost = PricingCatalog(strict_unknown_pricing=False).price_usage(
        model_name="missing",
        input_tokens=1,
        output_tokens=1,
        usage_source="estimated",
    )
    assert cost.cost_unknown is True
    assert cost.total_minor_units == 0


def test_cost_budget_idempotent_settlement_and_pending() -> None:
    context = make_context()
    manager = CostBudgetManager()

    reservation = manager.reserve(context, settlement_id="s1", amount_minor_units=5)
    assert manager.reserve(context, settlement_id="s1", amount_minor_units=5) is reservation
    assert manager.settle(reservation).status == "SETTLED"
    assert manager.settle(reservation).status == "SETTLED"
    assert manager.mark_pending("s2", 1).status == "COST_SETTLEMENT_PENDING"


def test_cost_budget_rejects_without_float_accounting() -> None:
    context = make_context()
    manager = CostBudgetManager()

    with pytest.raises(GovernanceError) as exc:
        manager.reserve(context, settlement_id="large", amount_minor_units=11)
    assert exc.value.error_code == "COST_BUDGET_EXCEEDED"
