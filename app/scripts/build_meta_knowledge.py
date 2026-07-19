from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.scripts.sync_metadata import default_meta_config_path, run_sync
from app.service.metadata_sync_service import MetadataSyncOptions


async def build(config_path: Path) -> dict[str, int | str | list[str]]:
    return await run_sync(config_path, MetadataSyncOptions(target="all"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Backward-compatible metadata build command.")
    parser.add_argument("-c", "--conf", type=Path, default=default_meta_config_path())
    args = parser.parse_args()
    asyncio.run(build(Path(args.conf)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
