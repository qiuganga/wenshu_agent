from app.core.events import AgentEvent, format_sse


def test_sse_format_contains_event_and_data():
    event = AgentEvent(
        request_id="rid",
        event="done",
        node=None,
        status="ok",
        message="done",
        sequence=1,
        elapsed_ms=1,
        data=None,
    )
    payload = format_sse(event)
    assert payload.startswith("event: done")
    assert "data:" in payload
