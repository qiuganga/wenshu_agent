from pathlib import Path

from scripts import check_no_secrets, check_readme_commands, check_text_encoding


def test_text_encoding_checker_detects_control_char(tmp_path: Path):
    bad = tmp_path / "bad.py"
    bad.write_bytes(b"print('x')\x07\n")
    issues = check_text_encoding.check_file(bad, tmp_path)
    assert any("control character" in issue for issue in issues)


def test_secret_checker_passes_current_repository():
    assert check_no_secrets.main() == 0


def test_readme_command_checker_passes_current_repository():
    assert check_readme_commands.main() == 0
