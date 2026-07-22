from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from app.config.app_config import RedisConfig, app_config


class RedisClientManager:
    def __init__(self, config: RedisConfig):
        self.config = config
        self.client: Redis | None = None

    def init(self) -> None:
        if self.config.password:
            auth_kwargs: Any = {"password": self.config.password}
            self.client = Redis(
                host=self.config.host,
                port=self.config.port,
                db=self.config.db,
                **auth_kwargs,
                socket_timeout=self.config.socket_timeout_seconds,
                socket_connect_timeout=self.config.socket_timeout_seconds,
                decode_responses=True,
            )
            return
        self.client = Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            socket_timeout=self.config.socket_timeout_seconds,
            socket_connect_timeout=self.config.socket_timeout_seconds,
            decode_responses=True,
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None


redis_client_manager = RedisClientManager(app_config.redis)
