from typing import TypeVar

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from typing_extensions import Generic

from app.config.app_config import app_config
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant

T = TypeVar("T")


class BaseQdrantRepository(Generic[T]):
    collection_name: str

    def __init__(self, client: AsyncQdrantClient):
        self.client = client

    async def ensure_collection(self):
        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(self.collection_name,
                                                vectors_config=VectorParams(size=app_config.qdrant.embedding_size,
                                                                            distance=Distance.COSINE))

    async def upsert(self, ids: list[str], embeddings: list[list[float]], payloads: list[T],
                     batch_size: int = 20):
        zipped = list(zip(ids, embeddings, payloads))
        for i in range(0, len(zipped), batch_size):
            batch = zipped[i:i + batch_size]
            batch_points = [PointStruct(id=id, vector=embedding, payload=payload) for id, embedding, payload in batch]
            await self.client.upsert(collection_name=self.collection_name, points=batch_points)

    async def search(self, embedding: list[float], score_threshold: float = 0.6, limit: int = 5) -> list[T]:
        if not await self.client.collection_exists(self.collection_name):
            return []
        result = await self.client.query_points(collection_name=self.collection_name,
                                                query=embedding,
                                                score_threshold=score_threshold,
                                                limit=limit)
        return [point.payload for point in result.points]

