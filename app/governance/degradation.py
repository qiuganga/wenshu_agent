from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DegradationDecision:
    action: str
    reason_codes: list[str]
    fail_closed: bool = False


class DegradationPolicy:
    def decide(
        self,
        *,
        dependency: str,
        safety_control: bool = False,
        fallback_available: bool = True,
    ) -> DegradationDecision:
        if safety_control:
            return DegradationDecision("fail_closed", [f"{dependency}_safety_dependency_unavailable"], fail_closed=True)
        if dependency == "semantic_cache" and fallback_available:
            return DegradationDecision("exact_cache", ["semantic_cache_unavailable"])
        if dependency == "telemetry":
            return DegradationDecision("noop", ["telemetry_exporter_unavailable"])
        if dependency == "evaluation":
            return DegradationDecision("skip_optional", ["evaluation_unavailable"])
        if dependency == "high_capability_model" and fallback_available:
            return DegradationDecision("fallback_model", ["high_capability_model_unavailable"])
        return DegradationDecision("fail_safe", [f"{dependency}_unavailable"], fail_closed=True)
