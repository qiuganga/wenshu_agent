from __future__ import annotations

from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    marker = root / "tmp_demo_bootstrap.json"
    if marker.exists():
        marker.unlink()
    print("Demo local marker cleaned. External demo databases are not modified by this offline reset command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
