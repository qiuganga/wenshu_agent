from __future__ import annotations

from pathlib import Path

TEXT_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".toml", ".prompt", ".json", ".sql"}
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
ALLOWED_CONTROL_CHARS = {"\n", "\r", "\t"}


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        yield path


def check_file(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root).as_posix()
    issues: list[str] = []
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        issues.append(f"{rel}:1: UTF-8 BOM is not allowed")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(f"{rel}:{exc.start}: invalid UTF-8: {exc.reason}")
        return issues
    for index, char in enumerate(text):
        codepoint = ord(char)
        if char == "\ufffd":
            issues.append(f"{rel}:{index}: replacement character U+FFFD is not allowed")
        elif codepoint < 32 and char not in ALLOWED_CONTROL_CHARS:
            issues.append(f"{rel}:{index}: ASCII control character U+{codepoint:04X} is not allowed")
    question_run = "?" * 4
    if question_run in text:
        issues.append(f"{rel}:{text.index(question_run)}: suspicious question-mark run")
    return issues


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues: list[str] = []
    for path in iter_text_files(root):
        issues.extend(check_file(path, root))
    if issues:
        print("Text encoding check failed:")
        print("\n".join(issues))
        return 1
    print("Text encoding check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
