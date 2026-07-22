from __future__ import annotations

import json
from typing import Any

from app.agents.handoff import sanitize_payload


class AgentMemory:
    def __init__(self, redis_client=None, key_prefix: str = "agent:memory", ttl_seconds: int = 3600) -> None:
        self.redis_client = redis_client
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self._local: dict[str, dict[str, Any]] = {}

    async def save(self, execution_id: str, values: dict[str, Any]) -> None:
        safe_values = sanitize_payload(values)
        if self.redis_client is None:
            self._local[execution_id] = safe_values
            return
        await self.redis_client.setex(
            self._key(execution_id),
            self.ttl_seconds,
            json.dumps(safe_values, ensure_ascii=False),
        )

    async def load(self, execution_id: str) -> dict[str, Any]:
        if self.redis_client is None:
            return dict(self._local.get(execution_id, {}))
        raw = await self.redis_client.get(self._key(execution_id))
        if raw is None:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def _key(self, execution_id: str) -> str:
        return f"{self.key_prefix}:{execution_id}"
