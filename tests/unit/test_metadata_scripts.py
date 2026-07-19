from argparse import Namespace
from pathlib import Path

import pytest

from app.scripts import bootstrap_demo, sync_metadata


@pytest.mark.asyncio
async def test_sync_metadata_script_returns_nonzero_on_external_error(monkeypatch):
    async def fake_run_sync(config_path, options):
        raise RuntimeError("external unavailable")

    monkeypatch.setattr(sync_metadata, "run_sync", fake_run_sync)
    monkeypatch.setattr(
        sync_metadata,
        "parse_args",
        lambda: Namespace(
            conf=Path("conf/meta_config.yaml"),
            target="all",
            dry_run=False,
            max_values_per_column=10,
            batch_size=5,
            fail_fast=True,
            recreate_index=False,
            recreate_collections=False,
        ),
    )

    assert await sync_metadata.async_main() == 1


@pytest.mark.asyncio
async def test_bootstrap_check_only_uses_dry_run(monkeypatch):
    captured = {}

    async def fake_run_sync(config_path, options):
        captured["dry_run"] = options.dry_run
        return {"status": "ok"}

    monkeypatch.setattr(bootstrap_demo, "run_sync", fake_run_sync)
    monkeypatch.setattr(
        bootstrap_demo,
        "parse_args",
        lambda: Namespace(
            check_only=True,
            sync_metadata=False,
            target="all",
            conf=Path("conf/meta_config.yaml"),
            max_values_per_column=10,
            batch_size=5,
        ),
    )

    assert await bootstrap_demo.async_main() == 0
    assert captured["dry_run"] is True
