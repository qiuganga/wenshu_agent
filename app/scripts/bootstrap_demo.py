from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config.app_config import app_config
from app.scripts.sync_metadata import default_meta_config_path, run_sync
from app.service.metadata_sync_service import MetadataSyncOptions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo bootstrap helper.")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--sync-metadata", action="store_true")
    parser.add_argument("--target", choices=["all", "qdrant", "es"], default="all")
    parser.add_argument("--conf", type=Path, default=default_meta_config_path())
    parser.add_argument("--max-values-per-column", type=int, default=app_config.metadata_sync.max_values_per_column)
    parser.add_argument("--batch-size", type=int, default=app_config.metadata_sync.batch_size)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    output: dict[str, object] = {
        "status": "ok",
        "meta_database": app_config.db_meta.database,
        "dw_database": app_config.db_dw.database,
        "metadata_config": str(args.conf),
        "message": "Demo bootstrap reads configured database names and only syncs metadata when explicitly requested.",
    }

    if args.check_only:
        summary = await run_sync(
            args.conf,
            MetadataSyncOptions(
                target=args.target,
                dry_run=True,
                max_values_per_column=args.max_values_per_column,
                batch_size=args.batch_size,
            ),
        )
        output["metadata_sync"] = summary
    elif args.sync_metadata:
        summary = await run_sync(
            args.conf,
            MetadataSyncOptions(
                target=args.target,
                dry_run=False,
                max_values_per_column=args.max_values_per_column,
                batch_size=args.batch_size,
            ),
        )
        output["metadata_sync"] = summary
    else:
        output["next_command"] = "uv run python -m app.scripts.bootstrap_demo --check-only"

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
