from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import Formatter
from typing import Any


@dataclass(frozen=True)
class PromptTemplateRecord:
    prompt_name: str
    version: str
    template_hash: str
    created_at: str
    variables: list[str]


class PromptTemplateManager:
    def __init__(self, *, prompt_dir: Path | None = None, version: str = "v1"):
        self.prompt_dir = prompt_dir or Path(__file__).parents[2] / "prompts"
        self.version = version

    def load_template(self, prompt_name: str) -> str:
        path = self.prompt_dir / f"{prompt_name}.prompt"
        return path.read_text(encoding="utf-8")

    def metadata(self, prompt_name: str) -> PromptTemplateRecord:
        template = self.load_template(prompt_name)
        path = self.prompt_dir / f"{prompt_name}.prompt"
        created_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        variables = sorted(
            {
                field_name
                for _, field_name, _, _ in Formatter().parse(template)
                if field_name and not field_name.isdigit()
            }
        )
        return PromptTemplateRecord(
            prompt_name=prompt_name,
            version=self.version,
            template_hash=self.template_hash(template),
            created_at=created_at,
            variables=variables,
        )

    def render(self, prompt_name: str, variables: dict[str, Any]) -> str:
        template = self.load_template(prompt_name)
        return template.format(**variables)

    @staticmethod
    def template_hash(template: str) -> str:
        return hashlib.sha256(template.encode("utf-8")).hexdigest()


prompt_template_manager = PromptTemplateManager()
