from elasticsearch import AsyncElasticsearch, NotFoundError

from app.config.app_config import app_config
from app.models.es.value_info_es import ValueInfoES


class ESBulkIndexError(RuntimeError):
    pass


class ValueESRepository:
    index_mappings = {
        "dynamic": False,
        "properties": {
            "id": {"type": "keyword"},
            "value": {"type": "text", "analyzer": "ik_max_word", "search_analyzer": "ik_max_word"},
            "type": {"type": "keyword"},
            "column_id": {"type": "keyword"},
            "column_name": {"type": "keyword"},
            "table_id": {"type": "keyword"},
            "table_name": {"type": "keyword"},
        },
    }

    def __init__(self, client: AsyncElasticsearch):
        self.client = client
        self.index_name = app_config.es.index_name

    async def ensure_index(self):
        if not await self.client.indices.exists(index=self.index_name):
            await self.client.indices.create(index=self.index_name, mappings=self.index_mappings)

    async def recreate_index(self):
        if await self.client.indices.exists(index=self.index_name):
            await self.client.indices.delete(index=self.index_name)
        await self.client.indices.create(index=self.index_name, mappings=self.index_mappings)

    async def index(self, value_infos, batch_size=20):
        for i in range(0, len(value_infos), batch_size):
            batch = value_infos[i : i + batch_size]
            operations = []
            for value_info in batch:
                operations.append({"index": {"_index": self.index_name, "_id": value_info["id"]}})
                operations.append(value_info)
            response = await self.client.bulk(operations=operations)
            if response.get("errors"):
                failures = []
                for item in response.get("items", [])[:5]:
                    action = item.get("index", {})
                    failures.append(
                        {
                            "id": action.get("_id"),
                            "status": action.get("status"),
                            "error_type": action.get("error", {}).get("type"),
                        }
                    )
                raise ESBulkIndexError(f"elasticsearch bulk index failed: {failures}")

    async def search(self, keyword: str, score_threshold: float = 0.6, limit: int = 5) -> list[ValueInfoES]:
        try:
            result = await self.client.search(
                index=self.index_name,
                query={"match": {"value": keyword}},
                min_score=score_threshold,
                size=limit,
            )
        except NotFoundError:
            return []
        return [hit["_source"] for hit in result["hits"]["hits"]]
