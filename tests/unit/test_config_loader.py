from dataclasses import dataclass

from app.config.config_loader import load_config


@dataclass
class SampleConfig:
    value: str = "default"


def test_load_config_uses_defaults_when_file_is_missing(tmp_path):
    config = load_config(SampleConfig, tmp_path / "missing.yaml")

    assert config.value == "default"
