from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.governance.common import GovernanceError


@dataclass(frozen=True)
class PricingEntry:
    provider: str
    model_name: str
    pricing_version: str
    effective_from: datetime
    input_price_per_million_tokens: Decimal
    output_price_per_million_tokens: Decimal
    currency: str
    source: str
    enabled: bool = True


@dataclass(frozen=True)
class CostBreakdown:
    model_name: str
    pricing_version: str
    currency: str
    input_minor_units: int
    output_minor_units: int
    total_minor_units: int
    usage_source: str
    cost_unknown: bool = False


class PricingCatalog:
    def __init__(
        self,
        entries: Iterable[PricingEntry] = (),
        *,
        strict_unknown_pricing: bool = True,
        minor_units_per_currency_unit: int = 100,
    ) -> None:
        self.strict_unknown_pricing = strict_unknown_pricing
        self.minor_units_per_currency_unit = minor_units_per_currency_unit
        self._entries: dict[str, PricingEntry] = {}
        for entry in entries:
            if entry.enabled:
                current = self._entries.get(entry.model_name)
                if current is None or current.effective_from <= entry.effective_from:
                    self._entries[entry.model_name] = entry

    def price_usage(
        self,
        *,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        usage_source: str,
    ) -> CostBreakdown:
        entry = self._entries.get(model_name)
        if entry is None:
            if self.strict_unknown_pricing:
                raise GovernanceError(
                    "COST_PRICING_UNKNOWN",
                    "Model pricing is unknown",
                    details={"usage_source": usage_source},
                )
            return CostBreakdown(model_name, "unknown", "UNKNOWN", 0, 0, 0, usage_source, cost_unknown=True)
        input_minor = self._tokens_to_minor(input_tokens, entry.input_price_per_million_tokens)
        output_minor = self._tokens_to_minor(output_tokens, entry.output_price_per_million_tokens)
        return CostBreakdown(
            model_name=model_name,
            pricing_version=entry.pricing_version,
            currency=entry.currency,
            input_minor_units=input_minor,
            output_minor_units=output_minor,
            total_minor_units=input_minor + output_minor,
            usage_source=usage_source,
        )

    def _tokens_to_minor(self, tokens: int, price_per_million: Decimal) -> int:
        if tokens <= 0:
            return 0
        units = (Decimal(tokens) / Decimal(1_000_000)) * price_per_million
        minor = units * Decimal(self.minor_units_per_currency_unit)
        return int(minor.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pricing_entry_from_config(config: Any, *, provider: str = "configured") -> PricingEntry:
    return PricingEntry(
        provider=provider,
        model_name=str(config.model_name),
        pricing_version=str(config.pricing_version),
        effective_from=datetime.fromisoformat(str(config.effective_from)).replace(tzinfo=UTC),
        input_price_per_million_tokens=Decimal(str(config.input_price_per_million_tokens)),
        output_price_per_million_tokens=Decimal(str(config.output_price_per_million_tokens)),
        currency=str(config.currency),
        source=str(config.source),
        enabled=bool(config.enabled),
    )
