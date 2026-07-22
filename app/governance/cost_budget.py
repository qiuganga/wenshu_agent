from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.governance.budget import BudgetContext
from app.governance.common import GovernanceError


@dataclass(frozen=True)
class CostReservation:
    settlement_id: str
    amount_minor_units: int
    status: str = "RESERVED"


class CostBudgetManager:
    def __init__(self) -> None:
        self._settlements: dict[str, CostReservation] = {}

    def reserve(self, context: BudgetContext, *, settlement_id: str, amount_minor_units: int) -> CostReservation:
        existing = self._settlements.get(settlement_id)
        if existing is not None:
            return existing
        if amount_minor_units < 0:
            raise ValueError("cost reservation must be non-negative")
        projected = context.consumed_cost + Decimal(amount_minor_units)
        if projected > context.max_cost:
            reservation = CostReservation(settlement_id, amount_minor_units, "REJECTED")
            self._settlements[settlement_id] = reservation
            raise GovernanceError("COST_BUDGET_EXCEEDED", "Cost budget exceeded")
        context.consumed_cost = projected
        reservation = CostReservation(settlement_id, amount_minor_units)
        self._settlements[settlement_id] = reservation
        return reservation

    def settle(self, reservation: CostReservation) -> CostReservation:
        existing = self._settlements.get(reservation.settlement_id)
        if existing is not None and existing.status == "SETTLED":
            return existing
        settled = CostReservation(reservation.settlement_id, reservation.amount_minor_units, "SETTLED")
        self._settlements[reservation.settlement_id] = settled
        return settled

    def release(self, context: BudgetContext, reservation: CostReservation) -> CostReservation:
        existing = self._settlements.get(reservation.settlement_id)
        if existing is not None and existing.status in {"SETTLED", "RELEASED"}:
            return existing
        context.consumed_cost = max(Decimal("0"), context.consumed_cost - Decimal(reservation.amount_minor_units))
        released = CostReservation(reservation.settlement_id, reservation.amount_minor_units, "RELEASED")
        self._settlements[reservation.settlement_id] = released
        return released

    def mark_pending(self, settlement_id: str, amount_minor_units: int) -> CostReservation:
        pending = CostReservation(settlement_id, amount_minor_units, "COST_SETTLEMENT_PENDING")
        self._settlements.setdefault(settlement_id, pending)
        return self._settlements[settlement_id]
