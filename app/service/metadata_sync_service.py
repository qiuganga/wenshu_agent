from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

from app.config.app_config import app_config
from app.config.meta_config import ColumnConfig, MetaConfig, MetricConfig, TableConfig
from app.core.logging import logger
from app.models.es.value_info_es import ValueInfoES
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant
from app.repository.es.value_es_repository import ValueESRepository
from app.repository.mysql.dw_mysql_repository import DWMySQLRepository
from app.repository.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repository.qdrant.metric_qdrant_repository import MetricQdrantRepository

SyncTarget = Literal["all", "qdrant", "es"]


class EmbeddingClient(Protocol):
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]: ...


class MetadataSyncError(RuntimeError):
    pass


@dataclass
class MetadataSyncOptions:
    target: SyncTarget = "all"
    dry_run: bool = False
    max_values_per_column: int = app_config.metadata_sync.max_values_per_column
    batch_size: int = app_config.metadata_sync.batch_size
    fail_fast: bool = True
    recreate_index: bool = False
    recreate_collections: bool = False


@dataclass
class MetadataSyncSummary:
    status: str = "ok"
    columns_indexed: int = 0
    metrics_indexed: int = 0
    value_documents_indexed: int = 0
    skipped_sensitive_columns: int = 0
    truncated_columns: int = 0
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, int | str | list[str]]:
        return {
            "status": self.status,
            "columns_indexed": self.columns_indexed,
            "metrics_indexed": self.metrics_indexed,
            "value_documents_indexed": self.value_documents_indexed,
            "skipped_sensitive_columns": self.skipped_sensitive_columns,
            "truncated_columns": self.truncated_columns,
            "duration_ms": self.duration_ms,
            "errors": self.errors,
        }


class MetadataSyncService:
    def __init__(
        self,
        *,
        dw_mysql_repository: DWMySQLRepository | None,
        column_qdrant_repository: ColumnQdrantRepository | None,
        metric_qdrant_repository: MetricQdrantRepository | None,
        value_es_repository: ValueESRepository | None,
        embedding_client: EmbeddingClient | None,
        sensitive_fields: list[str] | None = None,
    ) -> None:
        self.dw_mysql_repository = dw_mysql_repository
        self.column_qdrant_repository = column_qdrant_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.value_es_repository = value_es_repository
        self.embedding_client = embedding_client
        configured_sensitive_fields = sensitive_fields or app_config.security.sensitive_fields
        self.sensitive_fields = {field_name.lower() for field_name in configured_sensitive_fields}

    async def sync(self, meta_config: MetaConfig, options: MetadataSyncOptions) -> MetadataSyncSummary:
        started_at = time.perf_counter()
        summary = MetadataSyncSummary()
        try:
            if options.target in ("all", "qdrant"):
                await self.sync_qdrant(meta_config, options, summary)
            if options.target in ("all", "es"):
                await self.sync_es(meta_config, options, summary)
        except Exception as exc:
            summary.status = "error"
            summary.errors.append(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            summary.duration_ms = int((time.perf_counter() - started_at) * 1000)
        return summary

    async def sync_qdrant(
        self,
        meta_config: MetaConfig,
        options: MetadataSyncOptions,
        summary: MetadataSyncSummary | None = None,
    ) -> MetadataSyncSummary:
        summary = summary or MetadataSyncSummary()
        column_payloads = await self._build_column_payloads(meta_config, dry_run=options.dry_run)
        metric_payloads = [self._build_metric_payload(metric) for metric in meta_config.metrics]

        summary.columns_indexed += len(column_payloads)
        summary.metrics_indexed += len(metric_payloads)
        if options.dry_run:
            logger.info(
                "metadata qdrant dry-run columns={} metrics={}",
                len(column_payloads),
                len(metric_payloads),
            )
            return summary

        if self.column_qdrant_repository is None or self.metric_qdrant_repository is None:
            raise MetadataSyncError("qdrant repositories are required for qdrant sync")

        if options.recreate_collections:
            await self.column_qdrant_repository.recreate_collection()
            await self.metric_qdrant_repository.recreate_collection()
        else:
            await self.column_qdrant_repository.ensure_collection()
            await self.metric_qdrant_repository.ensure_collection()

        column_texts = [
            self._column_embedding_text(table, column) for table in meta_config.tables for column in table.columns
        ]
        column_embeddings = await self._embed_texts(column_texts)
        await self.column_qdrant_repository.upsert(
            [self.qdrant_point_id("column", payload["id"]) for payload in column_payloads],
            column_embeddings,
            column_payloads,
            batch_size=options.batch_size,
        )

        metric_texts = [self._metric_embedding_text(metric) for metric in meta_config.metrics]
        metric_embeddings = await self._embed_texts(metric_texts)
        await self.metric_qdrant_repository.upsert(
            [self.qdrant_point_id("metric", payload["id"]) for payload in metric_payloads],
            metric_embeddings,
            metric_payloads,
            batch_size=options.batch_size,
        )
        logger.info("metadata qdrant synced columns={} metrics={}", len(column_payloads), len(metric_payloads))
        return summary

    async def sync_es(
        self,
        meta_config: MetaConfig,
        options: MetadataSyncOptions,
        summary: MetadataSyncSummary | None = None,
    ) -> MetadataSyncSummary:
        summary = summary or MetadataSyncSummary()
        if options.dry_run:
            estimated_columns = sum(
                1
                for table in meta_config.tables
                for column in table.columns
                if column.sync and not self._is_sensitive_column(column)
            )
            summary.skipped_sensitive_columns += sum(
                1
                for table in meta_config.tables
                for column in table.columns
                if column.sync and self._is_sensitive_column(column)
            )
            logger.info("metadata es dry-run sync_columns={}", estimated_columns)
            return summary

        if self.dw_mysql_repository is None or self.value_es_repository is None:
            raise MetadataSyncError("dw mysql repository and es repository are required for es sync")

        if options.recreate_index:
            await self.value_es_repository.recreate_index()
        else:
            await self.value_es_repository.ensure_index()

        for table in meta_config.tables:
            sync_columns = [column for column in table.columns if column.sync]
            visible_sync_columns = [column for column in sync_columns if not self._is_sensitive_column(column)]
            skipped = len(sync_columns) - len(visible_sync_columns)
            summary.skipped_sensitive_columns += skipped
            for column in sync_columns:
                if self._is_sensitive_column(column):
                    logger.warning("metadata es skipped sensitive column_id={}", self.column_id(table, column))

            if not visible_sync_columns:
                continue

            column_types = await self.dw_mysql_repository.get_column_types(table.name)
            for column in visible_sync_columns:
                values = await self.dw_mysql_repository.get_column_values(
                    table.name,
                    column.name,
                    options.max_values_per_column + 1,
                )
                if len(values) > options.max_values_per_column:
                    summary.truncated_columns += 1
                    logger.warning("metadata es truncated column_id={}", self.column_id(table, column))
                value_infos = self._build_value_infos(
                    table,
                    column,
                    values[: options.max_values_per_column],
                    column_types.get(column.name) or column.type or "unknown",
                )
                if value_infos:
                    await self.value_es_repository.index(value_infos, batch_size=options.batch_size)
                    summary.value_documents_indexed += len(value_infos)

        logger.info(
            "metadata es synced value_documents={} skipped_sensitive={} truncated_columns={}",
            summary.value_documents_indexed,
            summary.skipped_sensitive_columns,
            summary.truncated_columns,
        )
        return summary

    async def _build_column_payloads(self, meta_config: MetaConfig, *, dry_run: bool) -> list[ColumnInfoQdrant]:
        payloads: list[ColumnInfoQdrant] = []
        for table in meta_config.tables:
            column_types: dict[str, str] = {}
            if not dry_run and self.dw_mysql_repository is not None:
                column_types = await self.dw_mysql_repository.get_column_types(table.name)
            for column in table.columns:
                payloads.append(
                    {
                        "id": self.column_id(table, column),
                        "name": column.name,
                        "type": column_types.get(column.name) or column.type or "unknown",
                        "role": column.role,
                        "examples": [],
                        "description": column.description,
                        "alias": column.alias,
                        "table_id": table.name,
                    }
                )
        return payloads

    def _build_metric_payload(self, metric: MetricConfig) -> MetricInfoQdrant:
        return {
            "id": self.metric_id(metric),
            "name": metric.name,
            "description": metric.description,
            "relevant_columns": metric.relevant_columns,
            "alias": metric.alias,
        }

    def _build_value_infos(
        self,
        table: TableConfig,
        column: ColumnConfig,
        values: list[Any],
        value_type: str,
    ) -> list[ValueInfoES]:
        normalized_values = self._normalize_values(values)
        column_id = self.column_id(table, column)
        return [
            {
                "id": self.value_id(table.name, column_id, value),
                "value": value,
                "type": value_type,
                "column_id": column_id,
                "column_name": column.name,
                "table_id": table.name,
                "table_name": table.name,
            }
            for value in normalized_values
        ]

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self.embedding_client is None:
            raise MetadataSyncError("embedding client is required for qdrant sync")
        embeddings = await self.embedding_client.aembed_documents(texts)
        expected_size = app_config.qdrant.embedding_size
        for index, embedding in enumerate(embeddings):
            if len(embedding) != expected_size:
                raise MetadataSyncError(
                    f"embedding dimension mismatch at index {index}: expected {expected_size}, got {len(embedding)}"
                )
        return embeddings

    def _normalize_values(self, values: list[Any]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized_value = self.normalize_value(value)
            if normalized_value is None or normalized_value in seen:
                continue
            normalized.append(normalized_value)
            seen.add(normalized_value)
        return normalized

    @staticmethod
    def normalize_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
        elif isinstance(value, Decimal):
            normalized = format(value, "f")
        else:
            normalized = str(value)
        return normalized or None

    @staticmethod
    def value_id(table_id: str, column_id: str, normalized_value: str) -> str:
        digest = hashlib.sha256(f"{table_id}\0{column_id}\0{normalized_value}".encode()).hexdigest()
        return digest

    @staticmethod
    def metric_id(metric: MetricConfig) -> str:
        return hashlib.sha256(f"metric\0{metric.name}".encode()).hexdigest()

    @staticmethod
    def column_id(table: TableConfig, column: ColumnConfig) -> str:
        return f"{table.name}.{column.name}"

    @staticmethod
    def qdrant_point_id(kind: str, stable_id: str) -> str:
        digest = hashlib.sha256(f"{kind}\0{stable_id}".encode()).hexdigest()
        return str(uuid.UUID(digest[:32]))

    def _is_sensitive_column(self, column: ColumnConfig) -> bool:
        return column.name.lower() in self.sensitive_fields

    @staticmethod
    def _column_embedding_text(table: TableConfig, column: ColumnConfig) -> str:
        alias = ", ".join(column.alias)
        return (
            f"table: {table.name}\n"
            f"table_description: {table.description}\n"
            f"column: {column.name}\n"
            f"column_description: {column.description}\n"
            f"role: {column.role}\n"
            f"alias: {alias}"
        )

    @staticmethod
    def _metric_embedding_text(metric: MetricConfig) -> str:
        alias = ", ".join(metric.alias)
        relevant_columns = ", ".join(metric.relevant_columns)
        return (
            f"metric: {metric.name}\n"
            f"metric_description: {metric.description}\n"
            f"alias: {alias}\n"
            f"relevant_columns: {relevant_columns}"
        )
