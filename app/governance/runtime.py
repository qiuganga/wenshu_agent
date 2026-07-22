from __future__ import annotations

from decimal import Decimal

from app.config.app_config import app_config
from app.governance.budget import BudgetContext, TokenBudgetManager
from app.governance.common import stable_hash
from app.governance.complexity import ComplexityResult, RequestComplexityClassifier


class GovernanceRuntime:
    def __init__(self) -> None:
        self.classifier = RequestComplexityClassifier()
        self.token_budget_manager = TokenBudgetManager()

    def build_budget_context(
        self,
        *,
        request_id: str,
        execution_id: str,
        user_id: str,
        tenant_id: str | None,
    ) -> BudgetContext:
        return BudgetContext(
            request_id=request_id,
            execution_id=execution_id,
            user_hash=stable_hash(user_id),
            tenant_hash=stable_hash(tenant_id or "default"),
            max_input_tokens=app_config.budget.request_max_total_tokens,
            max_output_tokens=app_config.budget.request_max_total_tokens,
            max_total_tokens=app_config.budget.request_max_total_tokens,
            max_cost=Decimal(app_config.budget.request_max_cost_minor_units),
            max_agent_steps=app_config.budget.request_max_agent_steps,
            max_llm_calls=app_config.budget.request_max_llm_calls,
            max_handoffs=app_config.budget.request_max_handoffs,
            max_runtime_seconds=app_config.agent.query_total_timeout_seconds,
            policy_version=app_config.governance.policy_version,
        )

    def classify(self, query: str) -> ComplexityResult:
        return self.classifier.classify(query)


governance_runtime = GovernanceRuntime()
