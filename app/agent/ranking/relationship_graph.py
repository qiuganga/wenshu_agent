from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class TableRelationship:
    source_table: str
    target_table: str
    confirmed: bool = True


class TableRelationshipGraph:
    def __init__(self, relationships: list[TableRelationship] | None = None, *, max_depth: int = 4) -> None:
        self.max_depth = max_depth
        self._edges: dict[str, set[str]] = {}
        for relationship in relationships or []:
            if not relationship.confirmed:
                continue
            self._edges.setdefault(relationship.source_table, set()).add(relationship.target_table)
            self._edges.setdefault(relationship.target_table, set()).add(relationship.source_table)

    def distance(self, source: str, target: str) -> int | None:
        if source == target:
            return 0
        if source not in self._edges or target not in self._edges:
            return None
        queue: deque[tuple[str, int]] = deque([(source, 0)])
        visited = {source}
        while queue:
            table, distance = queue.popleft()
            if distance >= self.max_depth:
                continue
            for neighbor in sorted(self._edges.get(table, ())):
                if neighbor == target:
                    return distance + 1
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, distance + 1))
        return None

    def connected(self, tables: list[str]) -> bool:
        unique_tables = list(dict.fromkeys(tables))
        if len(unique_tables) <= 1:
            return True
        anchor = unique_tables[0]
        return all(self.distance(anchor, table) is not None for table in unique_tables[1:])
