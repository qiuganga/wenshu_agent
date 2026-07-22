from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    description: str = ""

    def normalized(self) -> str:
        return self.name.strip().lower()


SQL_GENERATION = Capability("sql_generation", "Generate and execute governed SQL")
DOCUMENT_RETRIEVAL = Capability("document_retrieval", "Retrieve trusted context")
DATA_ANALYSIS = Capability("data_analysis", "Analyze data and explain trends")
CHART_GENERATION = Capability("chart_generation", "Generate chart-ready data")
