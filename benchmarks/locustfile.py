from __future__ import annotations

import json
import uuid

from locust import HttpUser, between, task


class QueryUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(3)
    def cache_hit_query(self) -> None:
        self._query("benchmark cache hit sales summary", "cache-hit")

    @task(2)
    def cache_miss_query(self) -> None:
        self._query(f"benchmark cache miss {uuid.uuid4().hex[:8]}", "cache-miss")

    @task(1)
    def timeout_query(self) -> None:
        self._query("benchmark slow model timeout scenario", "timeout")

    def _query(self, query: str, scenario: str) -> None:
        request_id = f"bench-{scenario}-{uuid.uuid4().hex}"
        with self.client.post(
            "/api/v1/query",
            data=json.dumps({"query": query, "request_id": request_id, "user_id": f"bench-{scenario}"}),
            headers={"Content-Type": "application/json", "X-Request-ID": request_id},
            name=f"/api/v1/query:{scenario}",
            stream=True,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")
                return
            for _line in response.iter_lines():
                pass
            response.success()
