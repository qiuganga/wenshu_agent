import pytest

from app.repository.es.value_es_repository import ESBulkIndexError, ValueESRepository


class FakeESClient:
    async def bulk(self, operations):
        return {
            "errors": True,
            "items": [
                {
                    "index": {
                        "_id": "value-id",
                        "status": 400,
                        "error": {"type": "mapper_parsing_exception", "reason": "failed hidden"},
                    }
                }
            ],
        }


@pytest.mark.asyncio
async def test_es_bulk_errors_raise():
    repository = ValueESRepository(FakeESClient())

    with pytest.raises(ESBulkIndexError, match="elasticsearch bulk index failed") as exc_info:
        await repository.index(
            [
                {
                    "id": "value-id",
                    "value": "hidden",
                    "type": "keyword",
                    "column_id": "fact_order.region",
                    "column_name": "region",
                    "table_id": "fact_order",
                    "table_name": "fact_order",
                }
            ]
        )
    assert "hidden" not in str(exc_info.value)
