from __future__ import annotations

import json
from pathlib import Path

DEMO_META_DB = "wenshu_meta_demo"
DEMO_DW_DB = "wenshu_dw_demo"


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    output = {
        "status": "ok",
        "meta_database": DEMO_META_DB,
        "dw_database": DEMO_DW_DB,
        "message": (
            "Demo bootstrap is idempotent. Start Docker dependencies, "
            "configure conf/app_config.yaml, then run the backend."
        ),
        "next_command": "uv run fastapi dev main.py",
    }
    (root / "tmp_demo_bootstrap.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
