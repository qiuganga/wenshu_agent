from types import SimpleNamespace

from app.repository.qdrant.base_qdrant_repository import BaseQdrantRepository


class FakeClient:
    async def collection_exists(self, collection_name):
        return True

    async def query_points(self, **kwargs):
        return SimpleNamespace(
            points=[
                SimpleNamespace(payload={"id": "a"}, score=0.7),
                SimpleNamespace(payload={"id": "b"}, score=float("nan")),
                SimpleNamespace(payload={"id": "c"}),
            ]
        )


class FakeRepository(BaseQdrantRepository[dict]):
    collection_name = "test"


async def test_search_with_scores_preserves_search_compatibility_and_sanitizes_scores() -> None:
    repository = FakeRepository(FakeClient())

    scored = await repository.search_with_scores([0.1, 0.2])
    payloads = await repository.search([0.1, 0.2])

    assert [candidate.score for candidate in scored] == [0.7, 0.0, 0.0]
    assert payloads == [{"id": "a"}, {"id": "b"}, {"id": "c"}]
