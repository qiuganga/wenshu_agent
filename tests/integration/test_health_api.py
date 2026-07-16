from starlette.testclient import TestClient

import main


def test_live_health():
    with TestClient(main.app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_empty_query_returns_422():
    with TestClient(main.app) as client:
        response = client.post("/api/v1/query", json={"query": "   "})
    assert response.status_code == 422


def test_request_id_header_is_returned():
    with TestClient(main.app) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "test-request-1"})
    assert response.headers["X-Request-ID"] == "test-request-1"
