from __future__ import annotations

from pathlib import Path
from typing import Any, Self

from omegaconf import OmegaConf
from pydantic import BaseModel, Field, model_validator


class ColumnConfig(BaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    description: str = Field(min_length=1)
    alias: list[str]
    sync: bool
    type: str | None = None


class TableConfig(BaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    description: str = Field(min_length=1)
    columns: list[ColumnConfig] = Field(min_length=1)


class MetricConfig(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    relevant_columns: list[str] = Field(min_length=1)
    alias: list[str]


class MetaConfig(BaseModel):
    tables: list[TableConfig] = Field(min_length=1)
    metrics: list[MetricConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        table_names: set[str] = set()
        column_ids: set[str] = set()
        metric_names: set[str] = set()

        for table in self.tables:
            if table.name in table_names:
                raise ValueError(f"duplicate table name: {table.name}")
            table_names.add(table.name)

            for column in table.columns:
                column_id = f"{table.name}.{column.name}"
                if column_id in column_ids:
                    raise ValueError(f"duplicate column id: {column_id}")
                column_ids.add(column_id)

        for metric in self.metrics:
            if metric.name in metric_names:
                raise ValueError(f"duplicate metric name: {metric.name}")
            metric_names.add(metric.name)

            for relevant_column in metric.relevant_columns:
                if relevant_column not in column_ids:
                    raise ValueError(f"metric {metric.name} references undefined column: {relevant_column}")

        return self

    def defined_column_ids(self) -> set[str]:
        return {f"{table.name}.{column.name}" for table in self.tables for column in table.columns}


def load_meta_config(config_path: str | Path) -> MetaConfig:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"meta config file does not exist: {path}")

    content = OmegaConf.load(path)
    data = OmegaConf.to_container(content, resolve=True)
    if not isinstance(data, dict):
        raise ValueError(f"meta config must be a mapping: {path}")
    return MetaConfig.model_validate(data if data is not None else {})


def load_meta_config_data(data: dict[str, Any]) -> MetaConfig:
    return MetaConfig.model_validate(data)
