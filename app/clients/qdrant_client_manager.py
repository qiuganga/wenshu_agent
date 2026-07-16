import asyncio

from qdrant_client import AsyncQdrantClient

from app.config.app_config import QdrantConfig, app_config


class QdrantClientManager:
    def __init__(self, config: QdrantConfig):
        self.config: QdrantConfig = config
        self.client: AsyncQdrantClient | None = None

    def _get_url(self):
        return f"http://127.0.0.1:{self.config.port}"

    def init(self):
        self.client = AsyncQdrantClient(url=self._get_url(), check_compatibility=False, trust_env=False)

    async def close(self):
        if self.client:
            await self.client.close()


qdrant_client_manager = QdrantClientManager(app_config.qdrant)


if __name__ == '__main__':
    async def test():
        qdrant_client_manager.init()

        try:
            collections = await qdrant_client_manager.client.get_collections()
            print("Qdrant 连接成功")
            print(collections)
        finally:
            await qdrant_client_manager.close()

    asyncio.run(test())