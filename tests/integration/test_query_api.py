from starlette.testclient import TestClient

import main
from app.api.dependencies import get_query_service


class FakeQueryService:
    async def query(self, query_request, request=None):
        yield 'event: started\ndata: {"event":"started","request_id":"rid"}\n\n'
        yield (
            'event: result\ndata: {"event":"result","data":{"final_answer":"ok","result_summary":{"row_count":1}}}\n\n'
        )
        yield 'event: done\ndata: {"event":"done"}\n\n'


class ErrorQueryService:
    async def query(self, query_request, request=None):
        yield 'event: started\ndata: {"event":"started"}\n\n'
        yield (
            "event: error\n"
            'data: {"event":"error","message":"Agent execution failed","data":{"code":"INTERNAL_ERROR"}}\n\n'
        )
        yield 'event: done\ndata: {"event":"done","status":"error"}\n\n'


def override_query_service(service):
    async def _override():
        return service

    return _override


def test_valid_query_returns_event_stream_and_headers():
    main.app.dependency_overrides[get_query_service] = override_query_service(FakeQueryService())
    try:
        with TestClient(main.app) as client:
            response = client.post("/api/v1/query", json={"query": "hello", "max_rows": 10})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        assert "event: started" in response.text
        assert "event: done" in response.text
        assert "rows" not in response.text
    finally:
        main.app.dependency_overrides.clear()


def test_api_validation_errors():
    with TestClient(main.app) as client:
        assert client.post("/api/v1/query", json={"query": ""}).status_code == 422
        assert client.post("/api/v1/query", json={"query": "x" * 2001}).status_code == 422
        assert client.post("/api/v1/query", json={"query": "ok", "max_rows": 999999}).status_code == 422


def test_request_id_reused_or_replaced():
    with TestClient(main.app) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "rid-1"})
        assert response.headers["X-Request-ID"] == "rid-1"
        invalid = client.get("/health/live", headers={"X-Request-ID": "??"})
        assert invalid.headers["X-Request-ID"] != "??"


def test_error_stream_is_sanitized():
    main.app.dependency_overrides[get_query_service] = override_query_service(ErrorQueryService())
    try:
        with TestClient(main.app) as client:
            response = client.post("/api/v1/query", json={"query": "hello"})
        assert response.status_code == 200
        assert "event: error" in response.text
        assert "password" not in response.text.lower()
        assert "127.0.0.1" not in response.text
    finally:
        main.app.dependency_overrides.clear()
