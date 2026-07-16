from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN_SNIPPETS = [
    "D:\\",
    "C:\\",
    "data-agent",
    "conf\x07pp_config",
]
REQUIRED_PATHS = [
    "conf/app_config.example.yaml",
    "conf/meta_config.yaml",
    "main.py",
    "app/scripts/bootstrap_demo.py",
    "app/scripts/reset_demo.py",
    "evals/run_evaluation.py",
    ".github/workflows/ci.yml",
]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    issues: list[str] = []
    for snippet in FORBIDDEN_SNIPPETS:
        if snippet in text:
            issues.append(f"README contains forbidden snippet: {snippet!r}")
    for match in re.finditer(r"[A-Za-z]:\\", text):
        issues.append(f"README contains absolute Windows path at offset {match.start()}")
    for path in REQUIRED_PATHS:
        if not (root / path).exists():
            issues.append(f"README references required path that does not exist yet: {path}")
    if "Copy-Item conf\\app_config.example.yaml conf\\app_config.yaml" not in text:
        issues.append("README must use escaped PowerShell Copy-Item command for app_config")
    if "cp conf/app_config.example.yaml conf/app_config.yaml" not in text:
        issues.append("README must include Linux/macOS cp command for app_config")
    if issues:
        print("README command check failed:")
        print("\n".join(issues))
        return 1
    print("README command check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
