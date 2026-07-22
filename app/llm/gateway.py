from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

from langchain_core.output_parsers import JsonOutputParser, PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ValidationError

from app.config.app_config import app_config
from app.core.telemetry import telemetry_manager
from app.llm.model_router import ModelRoute, ModelRouter, model_router
from app.llm.prompt_manager import PromptTemplateManager, prompt_template_manager
from app.llm.token_cost import CostTracker, TokenTracker

T = TypeVar("T", bound=BaseModel)


class LLMGatewayError(RuntimeError):
    pass


class LLMGateway:
    def __init__(
        self,
        *,
        router: ModelRouter | None = None,
        prompt_manager: PromptTemplateManager | None = None,
        token_tracker: TokenTracker | None = None,
        cost_tracker: CostTracker | None = None,
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        self.router = router or model_router
        self.prompt_manager = prompt_manager or prompt_template_manager
        self.token_tracker = token_tracker or TokenTracker()
        self.cost_tracker = cost_tracker or CostTracker(enabled=app_config.cost.enabled)
        self._sleep = sleep or asyncio.sleep
        self.last_model_name = ""
        self.last_fallback_used = False
        self.last_input_tokens = 0
        self.last_output_tokens = 0
        self.last_estimated_cost = 0.0

    async def ainvoke_text(self, prompt_name: str, payload: dict[str, Any]) -> str:
        response = await self._call_with_governance(prompt_name, payload, lambda client, prompt: prompt | client)
        return str(getattr(response, "content", response))

    async def ainvoke_json(self, prompt_name: str, payload: dict[str, Any]) -> Any:
        parser = JsonOutputParser()
        return await self._call_with_governance(prompt_name, payload, lambda client, prompt: prompt | client | parser)

    async def ainvoke_structured(
        self,
        prompt_name: str,
        payload: dict[str, Any],
        schema: type[T],
        parser: PydanticOutputParser | None = None,
    ) -> T:
        parser = parser or PydanticOutputParser(pydantic_object=schema)

        async def call_structured(client: Any, prompt: PromptTemplate) -> T:
            if hasattr(client, "with_structured_output"):
                try:
                    structured = client.with_structured_output(schema)
                    result = await structured.ainvoke(payload)
                    if isinstance(result, schema):
                        return result
                    return schema.model_validate(result)
                except NotImplementedError:
                    pass
                except ValidationError:
                    raise
            chain = prompt | client | parser
            return await chain.ainvoke(payload)

        return await self._call_with_governance(prompt_name, payload, call_structured)

    async def astream_text(self, prompt_name: str, payload: dict[str, Any]) -> AsyncIterator[str]:
        prompt_text = self.prompt_manager.render(prompt_name, payload)
        route = self.router.route(fallback=False)
        client = self.router.create_client(route.model_name)
        started = time.perf_counter()
        first_token_at: float | None = None
        output_parts: list[str] = []
        try:
            with telemetry_manager.span(
                "llm.request",
                {
                    "model_name": route.model_name,
                    "fallback_used": route.fallback_used,
                },
            ):
                prompt = PromptTemplate(
                    template=self.prompt_manager.load_template(prompt_name), input_variables=list(payload)
                )
                chain = prompt | client
                async for token in chain.astream(payload):
                    content = str(getattr(token, "content", token))
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    output_parts.append(content)
                    yield content
        except Exception as exc:
            if not self._is_retryable(exc) or not self.router.fallback_model:
                raise
            fallback_route = self.router.route(fallback=True)
            fallback_client = self.router.create_client(fallback_route.model_name)
            with telemetry_manager.span(
                "llm.request",
                {
                    "model_name": fallback_route.model_name,
                    "fallback_used": fallback_route.fallback_used,
                },
            ):
                prompt = PromptTemplate(
                    template=self.prompt_manager.load_template(prompt_name), input_variables=list(payload)
                )
                chain = prompt | fallback_client
                async for token in chain.astream(payload):
                    content = str(getattr(token, "content", token))
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    output_parts.append(content)
                    yield content
        finally:
            output_text = "".join(output_parts)
            self._record_usage(
                route=route,
                prompt_text=prompt_text,
                response_text=output_text,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            if first_token_at is not None:
                telemetry_manager.record_histogram("llm_latency_seconds", first_token_at - started)

    async def _call_with_governance(
        self,
        prompt_name: str,
        payload: dict[str, Any],
        call_factory: Callable[[Any, PromptTemplate], Any],
    ) -> Any:
        prompt_template = self.prompt_manager.load_template(prompt_name)
        prompt_text = self.prompt_manager.render(prompt_name, payload)
        primary = self.router.route(fallback=False)
        try:
            return await self._call_route(primary, prompt_template, prompt_text, payload, call_factory)
        except Exception as exc:
            if not self.router.fallback_model or not self._is_retryable(exc):
                raise
            fallback = self.router.route(fallback=True)
            return await self._call_route(fallback, prompt_template, prompt_text, payload, call_factory)

    async def _call_route(
        self,
        route: ModelRoute,
        prompt_template: str,
        prompt_text: str,
        payload: dict[str, Any],
        call_factory: Callable[[Any, PromptTemplate], Any],
    ) -> Any:
        attempts = max(1, app_config.llm.max_retries + 1)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                client = self.router.create_client(route.model_name)
                prompt = PromptTemplate(template=prompt_template, input_variables=list(payload))
                with telemetry_manager.span(
                    "llm.request",
                    {
                        "model_name": route.model_name,
                        "fallback_used": route.fallback_used,
                    },
                ):
                    chain_or_result = call_factory(client, prompt)
                    result = (
                        await chain_or_result.ainvoke(payload)
                        if hasattr(chain_or_result, "ainvoke")
                        else await chain_or_result
                    )
                response_text = str(getattr(result, "content", result))
                self._record_usage(
                    route=route,
                    prompt_text=prompt_text,
                    response_text=response_text,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                return result
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts - 1 or not self._is_retryable(exc):
                    raise
                await self._sleep(float(2**attempt))
        raise LLMGatewayError("LLM request failed") from last_exc

    def _record_usage(self, *, route: ModelRoute, prompt_text: str, response_text: str, latency_ms: int) -> None:
        usage = self.token_tracker.usage_for(prompt_text=prompt_text, response_text=response_text)
        cost = self.cost_tracker.estimate(route.model_name, usage)
        self.last_model_name = route.model_name
        self.last_fallback_used = route.fallback_used
        self.last_input_tokens = usage.input_tokens
        self.last_output_tokens = usage.output_tokens
        self.last_estimated_cost = cost.estimated_cost
        telemetry_manager.record_histogram(
            "llm_latency_seconds",
            latency_ms / 1000,
            attributes={
                "model_name": route.model_name,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "fallback_used": route.fallback_used,
                "latency_ms": latency_ms,
                "usage_source": cost.usage_source,
            },
        )
        telemetry_manager.record_histogram(
            "request_input_tokens",
            usage.input_tokens,
            attributes={"model_name": route.model_name, "usage_source": cost.usage_source},
        )
        telemetry_manager.record_histogram(
            "request_output_tokens",
            usage.output_tokens,
            attributes={"model_name": route.model_name, "usage_source": cost.usage_source},
        )
        telemetry_manager.record_histogram(
            "request_cost",
            cost.estimated_cost,
            attributes={"model_name": route.model_name, "usage_source": cost.usage_source},
        )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        text = f"{type(exc).__name__} {exc}".lower()
        return any(part in text for part in ("timeout", "network", "connection", "rate limit", "429"))


llm_gateway = LLMGateway()
