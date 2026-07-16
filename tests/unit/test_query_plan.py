from app.agent.state import create_initial_state


def test_initial_state_has_defaults():
    state = create_initial_state("  查询销售额  ")
    assert state["query"] == "查询销售额"
    assert state["retry_count"] == 0
    assert state["result"] == []
    assert state["error"] is None
