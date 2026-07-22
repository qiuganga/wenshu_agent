from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config.app_config import app_config
from app.governance.adaptive_router import AdaptiveModelRouter, ModelCandidate
from app.governance.complexity import ComplexityLevel


class MissingLLM:
    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("llm.api_key is not configured; configure conf/app_config.yaml before calling the LLM")


@dataclass(frozen=True)
class ModelRoute:
    model_name: str
    fallback_used: bool = False
    reason_codes: tuple[str, ...] = ()


class ModelRouter:
    def __init__(self) -> None:
        self.primary_model = app_config.llm.default_model or app_config.llm.model_name
        self.fallback_model = app_config.llm.fallback_model

    def route(self, *, fallback: bool = False) -> ModelRoute:
        if fallback and self.fallback_model:
            return ModelRoute(model_name=self.fallback_model, fallback_used=True, reason_codes=("fallback",))
        return ModelRoute(model_name=self.primary_model, fallback_used=False, reason_codes=("primary",))

    def route_adaptive(
        self,
        *,
        complexity: ComplexityLevel,
        remaining_tokens: int,
        remaining_cost_minor_units: int,
        required_capabilities: set[str] | None = None,
        structured_output_required: bool = False,
    ) -> ModelRoute:
        candidates = [
            ModelCandidate(
                model_name=self.primary_model,
                tier="standard",
                capabilities={"chat", "structured_output"},
                max_context_tokens=app_config.budget.request_max_total_tokens,
                cost_rank=2,
            )
        ]
        if self.fallback_model:
            candidates.append(
                ModelCandidate(
                    model_name=self.fallback_model,
                    tier="low",
                    capabilities={"chat", "structured_output"},
                    max_context_tokens=app_config.budget.request_max_total_tokens,
                    cost_rank=1,
                )
            )
        route = AdaptiveModelRouter(health_ttl_seconds=app_config.routing.model_health_ttl_seconds).route(
            complexity=complexity,
            candidates=candidates,
            required_capabilities=required_capabilities,
            remaining_tokens=remaining_tokens,
            remaining_cost_minor_units=remaining_cost_minor_units,
            structured_output_required=structured_output_required,
        )
        return ModelRoute(
            model_name=route.model_name,
            fallback_used=route.model_name == self.fallback_model,
            reason_codes=tuple(route.reason_codes),
        )

    def create_client(self, model_name: str) -> Any:
        if not app_config.llm.api_key.strip():
            return MissingLLM()
        return ChatOpenAI(
            model=model_name,
            api_key=SecretStr(app_config.llm.api_key),
            base_url=app_config.llm.base_url,
            temperature=app_config.llm.temperature,
            timeout=app_config.llm.timeout_seconds,
            max_retries=0,
        )


model_router = ModelRouter()
