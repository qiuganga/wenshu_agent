from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.config.app_config import app_config
from app.config.meta_config import load_meta_config
from app.repository.es.value_es_repository import ValueESRepository
from app.repository.mysql.dw_mysql_repository import DWMySQLRepository
from app.repository.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repository.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.service.metadata_sync_service import MetadataSyncOptions, MetadataSyncService


def default_meta_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "conf" / "meta_config.yaml"


async def run_sync(config_path: Path, options: MetadataSyncOptions) -> dict[str, int | str | list[str]]:
    meta_config = load_meta_config(config_path)
    if options.dry_run:
        service = MetadataSyncService(
            dw_mysql_repository=None,
            column_qdrant_repository=None,
            metric_qdrant_repository=None,
            value_es_repository=None,
            embedding_client=None,
        )
        return (await service.sync(meta_config, options)).to_dict()

    needs_qdrant = options.target in ("all", "qdrant")
    needs_es = options.target in ("all", "es")
    needs_dw = needs_qdrant or needs_es

    try:
        if needs_dw:
            dw_mysql_client_manager.init()
        if needs_qdrant:
            qdrant_client_manager.init()
            embedding_client_manager.init()
        if needs_es:
            es_client_manager.init()

        if dw_mysql_client_manager.session_factory is None:
            raise RuntimeError("DW MySQL session factory is not initialized")
        qdrant_client = qdrant_client_manager.client
        es_client = es_client_manager.client
        embedding_client = embedding_client_manager.client
        if needs_qdrant and (qdrant_client is None or embedding_client is None):
            raise RuntimeError("Qdrant or embedding client is not initialized")
        if needs_es and es_client is None:
            raise RuntimeError("Elasticsearch client is not initialized")
        async with dw_mysql_client_manager.session_factory() as dw_session:
            service = MetadataSyncService(
                dw_mysql_repository=DWMySQLRepository(dw_session) if needs_dw else None,
                column_qdrant_repository=ColumnQdrantRepository(qdrant_client) if needs_qdrant else None,
                metric_qdrant_repository=MetricQdrantRepository(qdrant_client) if needs_qdrant else None,
                value_es_repository=ValueESRepository(es_client) if needs_es else None,
                embedding_client=embedding_client if needs_qdrant else None,
            )
            return (await service.sync(meta_config, options)).to_dict()
    finally:
        await dw_mysql_client_manager.close()
        await qdrant_client_manager.close()
        await es_client_manager.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize metadata to Qdrant and Elasticsearch.")
    parser.add_argument("-c", "--conf", type=Path, default=default_meta_config_path())
    parser.add_argument("--target", choices=["all", "qdrant", "es"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-values-per-column", type=int, default=app_config.metadata_sync.max_values_per_column)
    parser.add_argument("--batch-size", type=int, default=app_config.metadata_sync.batch_size)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--recreate-index", action="store_true")
    parser.add_argument("--recreate-collections", action="store_true")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    options = MetadataSyncOptions(
        target=args.target,
        dry_run=args.dry_run,
        max_values_per_column=args.max_values_per_column,
        batch_size=args.batch_size,
        fail_fast=args.fail_fast,
        recreate_index=args.recreate_index,
        recreate_collections=args.recreate_collections,
    )
    try:
        summary = await run_sync(Path(args.conf), options)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        summary = {
            "status": "error",
            "columns_indexed": 0,
            "metrics_indexed": 0,
            "value_documents_indexed": 0,
            "skipped_sensitive_columns": 0,
            "truncated_columns": 0,
            "duration_ms": 0,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
