import asyncio

from elasticsearch import AsyncElasticsearch

from app.config.app_config import ESConfig, app_config


class ESClientManager:
    def __init__(self, config: ESConfig):
        self.config = config
        self.client: AsyncElasticsearch | None = None

    def _get_url(self):
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        self.client = AsyncElasticsearch(hosts=[self._get_url()])

    async def close(self):
        if self.client:
            await self.client.close()


es_client_manager = ESClientManager(app_config.es)


if __name__ == "__main__":
    async def test():
        es_client_manager.init()
        try:
            print(await es_client_manager.client.ping())
        finally:
            await es_client_manager.close()

    asyncio.run(test())
