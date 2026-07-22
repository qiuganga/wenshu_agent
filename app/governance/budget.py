from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.governance.common import GovernanceError


@dataclass
class BudgetContext:
    request_id: str
    execution_id: str
    user_hash: str
    tenant_hash: str
    max_input_tokens: int
    max_output_tokens: int
    max_total_tokens: int
    max_cost: Decimal
    max_agent_steps: int
    max_llm_calls: int
    max_handoffs: int
    max_runtime_seconds: float
    consumed_input_tokens: int = 0
    consumed_output_tokens: int = 0
    consumed_cost: Decimal = Decimal("0")
    consumed_agent_steps: int = 0
    consumed_llm_calls: int = 0
    consumed_handoffs: int = 0
    started_at: float = 0
    policy_version: str = "v1"

    def __post_init__(self) -> None:
        if self.started_at <= 0:
            self.started_at = time.monotonic()

    @property
    def consumed_total_tokens(self) -> int:
        return self.consumed_input_tokens + self.consumed_output_tokens

    @property
    def remaining_runtime_seconds(self) -> float:
        return max(0.0, self.max_runtime_seconds - (time.monotonic() - self.started_at))

    def safe_snapshot(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "execution_id": self.execution_id,
            "user_hash": self.user_hash,
            "tenant_hash": self.tenant_hash,
            "max_total_tokens": self.max_total_tokens,
            "consumed_total_tokens": self.consumed_total_tokens,
            "consumed_llm_calls": self.consumed_llm_calls,
            "consumed_agent_steps": self.consumed_agent_steps,
            "consumed_handoffs": self.consumed_handoffs,
            "remaining_runtime_seconds": self.remaining_runtime_seconds,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class TokenReservation:
    reservation_id: str
    input_tokens: int
    output_tokens: int
    settled: bool = False


class TokenBudgetManager:
    def reserve_llm_call(
        self,
        context: BudgetContext,
        *,
        reservation_id: str,
        estimated_input_tokens: int,
        max_output_tokens: int,
    ) -> TokenReservation:
        if context.consumed_llm_calls + 1 > context.max_llm_calls:
            raise GovernanceError("TOKEN_BUDGET_EXCEEDED", "LLM call budget exceeded")
        if estimated_input_tokens < 0 or max_output_tokens < 0:
            raise ValueError("token reservations must be non-negative")
        projected_input = context.consumed_input_tokens + estimated_input_tokens
        projected_output = context.consumed_output_tokens + max_output_tokens
        if projected_input > context.max_input_tokens or projected_output > context.max_output_tokens:
            raise GovernanceError("TOKEN_BUDGET_EXCEEDED", "Token budget exceeded")
        if projected_input + projected_output > context.max_total_tokens:
            raise GovernanceError("TOKEN_BUDGET_EXCEEDED", "Total token budget exceeded")
        context.consumed_input_tokens = projected_input
        context.consumed_output_tokens = projected_output
        context.consumed_llm_calls += 1
        return TokenReservation(reservation_id, estimated_input_tokens, max_output_tokens)

    def settle_llm_call(
        self,
        context: BudgetContext,
        reservation: TokenReservation,
        *,
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> TokenReservation:
        if reservation.settled:
            return reservation
        if actual_input_tokens < 0 or actual_output_tokens < 0:
            raise ValueError("actual token usage must be non-negative")
        context.consumed_input_tokens -= reservation.input_tokens
        context.consumed_output_tokens -= reservation.output_tokens
        projected_input = context.consumed_input_tokens + actual_input_tokens
        projected_output = context.consumed_output_tokens + actual_output_tokens
        if projected_input + projected_output > context.max_total_tokens:
            raise GovernanceError("TOKEN_BUDGET_EXCEEDED", "Actual token usage exceeded budget")
        context.consumed_input_tokens = projected_input
        context.consumed_output_tokens = projected_output
        return TokenReservation(reservation.reservation_id, actual_input_tokens, actual_output_tokens, settled=True)

    def release(self, context: BudgetContext, reservation: TokenReservation) -> None:
        if reservation.settled:
            return
        context.consumed_input_tokens = max(0, context.consumed_input_tokens - reservation.input_tokens)
        context.consumed_output_tokens = max(0, context.consumed_output_tokens - reservation.output_tokens)
        context.consumed_llm_calls = max(0, context.consumed_llm_calls - 1)

    def record_agent_step(self, context: BudgetContext) -> None:
        if context.consumed_agent_steps + 1 > context.max_agent_steps:
            raise GovernanceError("AGENT_STEP_LIMIT_EXCEEDED", "Agent step budget exceeded")
        context.consumed_agent_steps += 1

    def record_handoff(self, context: BudgetContext) -> None:
        if context.consumed_handoffs + 1 > context.max_handoffs:
            raise GovernanceError("HANDOFF_LIMIT_EXCEEDED", "Handoff budget exceeded")
        context.consumed_handoffs += 1
