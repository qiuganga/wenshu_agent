from typing import Any, cast

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.agent.ranking.models import ScoredCandidate
from app.agent.ranking.normalization import safe_similarity_score
from app.config.app_config import app_config


class BaseQdrantRepository[T]:
    collection_name: str

    def __init__(self, client: AsyncQdrantClient):
        self.client = client

    async def ensure_collection(self):
        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(
                self.collection_name,
                vectors_config=VectorParams(size=app_config.qdrant.embedding_size, distance=Distance.COSINE),
            )

    async def recreate_collection(self):
        if await self.client.collection_exists(self.collection_name):
            await self.client.delete_collection(self.collection_name)
        await self.client.create_collection(
            self.collection_name,
            vectors_config=VectorParams(size=app_config.qdrant.embedding_size, distance=Distance.COSINE),
        )

    async def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        payloads: list[T],
        batch_size: int = 20,
    ):
        zipped = list(zip(ids, embeddings, payloads, strict=True))
        for i in range(0, len(zipped), batch_size):
            batch = zipped[i : i + batch_size]
            batch_points = [
                PointStruct(id=id_, vector=embedding, payload=cast(dict[str, Any], payload))
                for id_, embedding, payload in batch
            ]
            await self.client.upsert(collection_name=self.collection_name, points=batch_points)

    async def search(self, embedding: list[float], score_threshold: float = 0.6, limit: int = 5) -> list[T]:
        scored = await self.search_with_scores(embedding, score_threshold=score_threshold, limit=limit)
        return [candidate.payload for candidate in scored]

    async def search_with_scores(
        self,
        embedding: list[float],
        score_threshold: float = 0.6,
        limit: int = 5,
    ) -> list[ScoredCandidate[T]]:
        if not await self.client.collection_exists(self.collection_name):
            return []
        result = await self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            score_threshold=score_threshold,
            limit=limit,
        )
        return [
            ScoredCandidate(cast(T, point.payload), safe_similarity_score(getattr(point, "score", None)))
            for point in result.points
        ]
