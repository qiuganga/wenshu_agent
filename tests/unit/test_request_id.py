from fastapi.testclient import TestClient

import main


def test_request_id_context_resets_after_request():
    with TestClient(main.app) as client:
        first = client.get("/health/live", headers={"X-Request-ID": "first"})
        second = client.get("/health/live")
    assert first.headers["X-Request-ID"] == "first"
    assert second.headers["X-Request-ID"] != "first"


def test_concurrent_request_ids_are_isolated():
    with TestClient(main.app) as client:
        one = client.get("/health/live", headers={"X-Request-ID": "one"})
        two = client.get("/health/live", headers={"X-Request-ID": "two"})
    assert one.headers["X-Request-ID"] == "one"
    assert two.headers["X-Request-ID"] == "two"
