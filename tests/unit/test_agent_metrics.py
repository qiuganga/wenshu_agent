from app.evaluation.agent_metrics import evaluate_agent_routing


def test_agent_metrics_evaluate_selection_handoff_and_latency() -> None:
    scores = {
        metric.name: metric.score
        for metric in evaluate_agent_routing(
            selected_agents=["sql_agent", "analysis_agent"],
            expected_agents=["sql_agent", "analysis_agent"],
            handoff_attempts=1,
            handoff_successes=1,
            routing_latency_ms=50,
        )
    }

    assert scores["agent_selection_accuracy"] == 1.0
    assert scores["handoff_success_rate"] == 1.0
    assert scores["routing_latency"] == 1.0


def test_agent_metrics_detect_partial_selection_and_failed_handoff() -> None:
    scores = {
        metric.name: metric.score
        for metric in evaluate_agent_routing(
            selected_agents=["sql_agent"],
            expected_agents=["sql_agent", "analysis_agent"],
            handoff_attempts=2,
            handoff_successes=1,
            routing_latency_ms=600,
        )
    }

    assert scores["agent_selection_accuracy"] == 0.5
    assert scores["handoff_success_rate"] == 0.5
    assert 0 < scores["routing_latency"] < 1
