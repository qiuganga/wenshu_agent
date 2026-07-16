from __future__ import annotations

import re
from pathlib import Path

TEXT_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".toml", ".prompt", ".json", ".sql"}
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "tests"}
EXCLUDED_FILES = {"conf/app_config.yaml"}
PLACEHOLDER_PATTERNS = (
    "your_api_key_here",
    "your_siliconflow_api_key_here",
    "change_me",
    "changeme",
    "sk-xxx",
    "***",
)
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"]?(?!your_|sk-xxx|\*\*\*)[A-Za-z0-9_./+=-]{12,}"),
    re.compile(r"(?i)password\s*[:=]\s*['\"]?(?!change_me|changeme|\*\*\*)[^\s'\"]{8,}"),
    re.compile(r"(?i)(mysql|postgresql|postgres)\+?[a-z0-9]*://[^\s]+:[^\s]+@"),
]


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in EXCLUDED_FILES or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        yield path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings: list[str] = []
    for path in iter_text_files(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if "request_id_ctx_var" in lowered or "reset(token)" in lowered:
                continue
            if any(placeholder in lowered for placeholder in PLACEHOLDER_PATTERNS):
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{rel}:{lineno}: possible secret: {pattern.pattern}")
    if findings:
        print("Secret check failed:")
        print("\n".join(findings))
        return 1
    print("Secret check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
