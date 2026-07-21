from uuid import UUID

import pytest

from app.config.app_config import app_config
from app.config.meta_config import load_meta_config_data
from app.service.metadata_sync_service import MetadataSyncError, MetadataSyncOptions, MetadataSyncService


class FakeDWRepository:
    def __init__(self, values=None):
        self.values = values or []
        self.get_column_values_calls = []
        self.get_column_types_calls = []

    async def get_column_types(self, table_name):
        self.get_column_types_calls.append(table_name)
        return {"region": "varchar(32)", "password": "varchar(128)", "amount": "decimal(10,2)"}

    async def get_column_values(self, table_name, column_name, limit):
        self.get_column_values_calls.append((table_name, column_name, limit))
        return self.values


class FakeESRepository:
    def __init__(self):
        self.ensure_index_calls = 0
        self.recreate_index_calls = 0
        self.index_calls = []

    async def ensure_index(self):
        self.ensure_index_calls += 1

    async def recreate_index(self):
        self.recreate_index_calls += 1

    async def index(self, value_infos, batch_size=20):
        self.index_calls.append((value_infos, batch_size))


class FakeQdrantRepository:
    def __init__(self):
        self.ensure_collection_calls = 0
        self.recreate_collection_calls = 0
        self.upsert_calls = []

    async def ensure_collection(self):
        self.ensure_collection_calls += 1

    async def recreate_collection(self):
        self.recreate_collection_calls += 1

    async def upsert(self, ids, embeddings, payloads, batch_size=20):
        self.upsert_calls.append((ids, embeddings, payloads, batch_size))


class FakeEmbeddingClient:
    def __init__(self, dimension=None):
        self.dimension = dimension or app_config.qdrant.embedding_size
        self.calls = []

    async def aembed_documents(self, texts):
        self.calls.append(texts)
        return [[0.1] * self.dimension for _ in texts]


def _meta_config(*, sync=False, column_name="region"):
    return load_meta_config_data(
        {
            "tables": [
                {
                    "name": "fact_order",
                    "role": "fact",
                    "description": "orders",
                    "columns": [
                        {
                            "name": column_name,
                            "role": "dimension",
                            "description": "region",
                            "alias": ["area"],
                            "sync": sync,
                        }
                    ],
                }
            ],
            "metrics": [
                {
                    "name": "GMV",
                    "description": "total amount",
                    "relevant_columns": [f"fact_order.{column_name}"],
                    "alias": ["sales"],
                }
            ],
        }
    )


def _service(dw=None, es=None, column_qdrant=None, metric_qdrant=None, embedding=None, sensitive_fields=None):
    return MetadataSyncService(
        dw_mysql_repository=dw,
        column_qdrant_repository=column_qdrant,
        metric_qdrant_repository=metric_qdrant,
        value_es_repository=es,
        embedding_client=embedding,
        sensitive_fields=sensitive_fields or ["password"],
    )


@pytest.mark.asyncio
async def test_sync_false_does_not_read_dw_values():
    dw = FakeDWRepository()
    es = FakeESRepository()
    service = _service(dw=dw, es=es)

    summary = await service.sync_es(_meta_config(sync=False), MetadataSyncOptions(target="es"))

    assert summary.value_documents_indexed == 0
    assert dw.get_column_values_calls == []
    assert dw.get_column_types_calls == []


@pytest.mark.asyncio
async def test_sync_true_reads_dw_values():
    dw = FakeDWRepository(values=["north"])
    es = FakeESRepository()
    service = _service(dw=dw, es=es)

    summary = await service.sync_es(_meta_config(sync=True), MetadataSyncOptions(target="es"))

    assert dw.get_column_values_calls == [("fact_order", "region", app_config.metadata_sync.max_values_per_column + 1)]
    assert summary.value_documents_indexed == 1


@pytest.mark.asyncio
async def test_null_empty_and_duplicate_values_are_filtered():
    dw = FakeDWRepository(values=[None, " north ", "", "north", "south"])
    es = FakeESRepository()
    service = _service(dw=dw, es=es)

    summary = await service.sync_es(_meta_config(sync=True), MetadataSyncOptions(target="es"))

    indexed_values = [item["value"] for item in es.index_calls[0][0]]
    assert indexed_values == ["north", "south"]
    assert summary.value_documents_indexed == 2


@pytest.mark.asyncio
async def test_sensitive_field_is_skipped():
    dw = FakeDWRepository(values=["secret"])
    es = FakeESRepository()
    service = _service(dw=dw, es=es, sensitive_fields=["password"])

    summary = await service.sync_es(_meta_config(sync=True, column_name="password"), MetadataSyncOptions(target="es"))

    assert summary.skipped_sensitive_columns == 1
    assert dw.get_column_values_calls == []
    assert es.index_calls == []


def test_value_id_is_stable_and_scoped_by_field():
    first = MetadataSyncService.value_id("fact_order", "fact_order.region", "north")
    second = MetadataSyncService.value_id("fact_order", "fact_order.region", "north")
    other_field = MetadataSyncService.value_id("fact_order", "fact_order.city", "north")

    assert first == second
    assert first != other_field


def test_qdrant_point_id_is_deterministic_uuid_and_scoped_by_kind():
    first = MetadataSyncService.qdrant_point_id("column", "fact_order.region")
    second = MetadataSyncService.qdrant_point_id("column", "fact_order.region")
    metric = MetadataSyncService.qdrant_point_id("metric", "fact_order.region")

    assert first == second
    assert first != "fact_order.region"
    assert first != metric
    assert str(UUID(first)) == first


@pytest.mark.asyncio
async def test_qdrant_ids_are_stable_across_runs():
    dw = FakeDWRepository()
    column_repo = FakeQdrantRepository()
    metric_repo = FakeQdrantRepository()
    embedding = FakeEmbeddingClient()
    service = _service(dw=dw, column_qdrant=column_repo, metric_qdrant=metric_repo, embedding=embedding)
    config = _meta_config(sync=False)

    await service.sync_qdrant(config, MetadataSyncOptions(target="qdrant"))
    await service.sync_qdrant(config, MetadataSyncOptions(target="qdrant"))

    first_column_ids = column_repo.upsert_calls[0][0]
    second_column_ids = column_repo.upsert_calls[1][0]
    first_metric_ids = metric_repo.upsert_calls[0][0]
    second_metric_ids = metric_repo.upsert_calls[1][0]
    assert first_column_ids == [MetadataSyncService.qdrant_point_id("column", "fact_order.region")]
    assert column_repo.upsert_calls[0][2][0]["id"] == "fact_order.region"
    assert first_column_ids == second_column_ids
    assert first_metric_ids == second_metric_ids


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_fails():
    dw = FakeDWRepository()
    column_repo = FakeQdrantRepository()
    metric_repo = FakeQdrantRepository()
    service = _service(
        dw=dw,
        column_qdrant=column_repo,
        metric_qdrant=metric_repo,
        embedding=FakeEmbeddingClient(dimension=1),
    )

    with pytest.raises(MetadataSyncError, match="embedding dimension mismatch"):
        await service.sync_qdrant(_meta_config(sync=False), MetadataSyncOptions(target="qdrant"))


@pytest.mark.asyncio
async def test_dry_run_does_not_write_to_qdrant_or_es():
    dw = FakeDWRepository(values=["north"])
    es = FakeESRepository()
    column_repo = FakeQdrantRepository()
    metric_repo = FakeQdrantRepository()
    service = _service(
        dw=dw,
        es=es,
        column_qdrant=column_repo,
        metric_qdrant=metric_repo,
        embedding=FakeEmbeddingClient(),
    )

    summary = await service.sync(_meta_config(sync=True), MetadataSyncOptions(target="all", dry_run=True))

    assert summary.columns_indexed == 1
    assert summary.metrics_indexed == 1
    assert es.index_calls == []
    assert column_repo.upsert_calls == []
    assert metric_repo.upsert_calls == []


@pytest.mark.asyncio
async def test_value_sync_truncates_at_limit():
    dw = FakeDWRepository(values=["a", "b", "c"])
    es = FakeESRepository()
    service = _service(dw=dw, es=es)

    summary = await service.sync_es(
        _meta_config(sync=True),
        MetadataSyncOptions(target="es", max_values_per_column=2),
    )

    indexed_values = [item["value"] for item in es.index_calls[0][0]]
    assert indexed_values == ["a", "b"]
    assert summary.truncated_columns == 1
    assert summary.value_documents_indexed == 2
