from __future__ import annotations

from app.evaluation.metrics import MetricResult


def evaluate_agent_routing(
    *,
    selected_agents: list[str],
    expected_agents: list[str],
    handoff_attempts: int = 0,
    handoff_successes: int = 0,
    routing_latency_ms: int = 0,
) -> list[MetricResult]:
    selected = {agent for agent in selected_agents if agent}
    expected = {agent for agent in expected_agents if agent}
    selection_accuracy = len(selected & expected) / len(expected) if expected else 1.0
    handoff_success_rate = handoff_successes / handoff_attempts if handoff_attempts else 1.0
    routing_latency_score = 1.0 if routing_latency_ms <= 100 else max(0.0, 1 - ((routing_latency_ms - 100) / 1000))
    return [
        MetricResult("agent_selection_accuracy", selection_accuracy),
        MetricResult("handoff_success_rate", handoff_success_rate),
        MetricResult("routing_latency", routing_latency_score, {"latency_ms": routing_latency_ms}),
    ]
