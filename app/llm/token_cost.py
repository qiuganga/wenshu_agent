from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenTracker:
    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def usage_for(self, *, prompt_text: str, response_text: str) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.estimate_tokens(prompt_text),
            output_tokens=self.estimate_tokens(response_text),
        )


@dataclass(frozen=True)
class CostEstimate:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float
    usage_source: str = "estimated"


class CostTracker:
    def __init__(self, *, enabled: bool = True, cost_per_1k_tokens: dict[str, float] | None = None):
        self.enabled = enabled
        self.cost_per_1k_tokens = cost_per_1k_tokens or {}

    def estimate(self, model: str, usage: TokenUsage) -> CostEstimate:
        rate = self.cost_per_1k_tokens.get(model, 0.0) if self.enabled else 0.0
        return CostEstimate(
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            estimated_cost=(usage.total_tokens / 1000) * rate,
            usage_source="estimated",
        )
