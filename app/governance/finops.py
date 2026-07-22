from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FinOpsRecord:
    time_bucket: str
    tenant_hash: str
    model_name: str
    agent_name: str
    cache_hit: bool
    usage_source: str
    pricing_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_minor_units: int = 0
    provider_reported_cost_minor_units: int | None = None
    cache_saved_tokens: int = 0
    cache_saved_cost_estimate_minor_units: int = 0
    fallback_cost_minor_units: int = 0
    retry_cost_minor_units: int = 0
    handoff_cost_minor_units: int = 0


class FinOpsAggregator:
    def __init__(self) -> None:
        self._records: list[FinOpsRecord] = []

    def add(self, record: FinOpsRecord) -> None:
        self._records.append(record)

    def aggregate(self) -> list[dict[str, object]]:
        totals: dict[tuple[object, ...], dict[str, Any]] = {}
        for record in self._records:
            key = (
                record.time_bucket,
                record.tenant_hash,
                record.model_name,
                record.agent_name,
                record.cache_hit,
                record.usage_source,
                record.pricing_version,
            )
            bucket = totals.setdefault(
                key,
                {
                    "time_bucket": record.time_bucket,
                    "tenant_hash": record.tenant_hash,
                    "model_name": record.model_name,
                    "agent_name": record.agent_name,
                    "cache_hit": record.cache_hit,
                    "usage_source": record.usage_source,
                    "pricing_version": record.pricing_version,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_minor_units": 0,
                    "provider_reported_cost_minor_units": 0,
                    "request_count": 0,
                    "cache_saved_tokens": 0,
                    "cache_saved_cost_estimate_minor_units": 0,
                    "fallback_cost_minor_units": 0,
                    "retry_cost_minor_units": 0,
                    "handoff_cost_minor_units": 0,
                },
            )
            bucket["input_tokens"] = int(bucket["input_tokens"]) + record.input_tokens
            bucket["output_tokens"] = int(bucket["output_tokens"]) + record.output_tokens
            bucket["total_tokens"] = int(bucket["total_tokens"]) + record.input_tokens + record.output_tokens
            bucket["estimated_cost_minor_units"] = (
                int(bucket["estimated_cost_minor_units"]) + record.estimated_cost_minor_units
            )
            bucket["request_count"] = int(bucket["request_count"]) + 1
            bucket["cache_saved_tokens"] = int(bucket["cache_saved_tokens"]) + record.cache_saved_tokens
            bucket["cache_saved_cost_estimate_minor_units"] = (
                int(bucket["cache_saved_cost_estimate_minor_units"]) + record.cache_saved_cost_estimate_minor_units
            )
            bucket["fallback_cost_minor_units"] = (
                int(bucket["fallback_cost_minor_units"]) + record.fallback_cost_minor_units
            )
            bucket["retry_cost_minor_units"] = int(bucket["retry_cost_minor_units"]) + record.retry_cost_minor_units
            bucket["handoff_cost_minor_units"] = (
                int(bucket["handoff_cost_minor_units"]) + record.handoff_cost_minor_units
            )
            if record.provider_reported_cost_minor_units is not None:
                bucket["provider_reported_cost_minor_units"] = (
                    int(bucket["provider_reported_cost_minor_units"]) + record.provider_reported_cost_minor_units
                )
        return list(totals.values())
