from app.llm.token_cost import CostTracker, TokenTracker


def test_token_tracker_estimates_usage_without_text_capture():
    tracker = TokenTracker()

    usage = tracker.usage_for(prompt_text="abcd" * 10, response_text="ok" * 10)

    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.total_tokens == 15


def test_cost_tracker_estimates_model_cost():
    tracker = CostTracker(enabled=True, cost_per_1k_tokens={"model-a": 0.2})
    usage = TokenTracker().usage_for(prompt_text="abcd" * 100, response_text="abcd" * 50)

    cost = tracker.estimate("model-a", usage)

    assert cost.model == "model-a"
    assert cost.total_tokens == 150
    assert cost.estimated_cost == 0.03


def test_cost_tracker_can_be_disabled():
    tracker = CostTracker(enabled=False, cost_per_1k_tokens={"model-a": 100})
    usage = TokenTracker().usage_for(prompt_text="abcd", response_text="abcd")

    assert tracker.estimate("model-a", usage).estimated_cost == 0
