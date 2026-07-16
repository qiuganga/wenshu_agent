from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app_config import app_config
from app.core.logging import logger


class QueryExecutionResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: int = 0


class DWMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        result = await self.session.execute(text(f"show columns from {table_name}"))
        return {row.Field: row.Type for row in result.fetchall()}

    async def get_column_values(self, table_name: str, column_name: str, limit: int):
        safe_limit = min(limit, 100000)
        result = await self.session.execute(text(f"select distinct {column_name} from {table_name} limit {safe_limit}"))
        return result.scalars().fetchall()

    async def get_db_info(self):
        result = await self.session.execute(text("select version()"))
        version = result.scalar()
        dialect = self.session.get_bind().dialect.name
        return {"version": version, "dialect": dialect}

    async def validate_sql(self, sql: str):
        await self.session.execute(text(f"explain {sql}"))

    async def _best_effort_readonly_session(self, timeout_seconds: int) -> None:
        timeout_ms = max(1, int(timeout_seconds * 1000))
        for statement in (f"SET SESSION MAX_EXECUTION_TIME={timeout_ms}", "START TRANSACTION READ ONLY"):
            try:
                await self.session.execute(text(statement))
            except Exception as exc:  # pragma: no cover - depends on database flavor and permissions
                logger.warning(f"readonly session setup skipped statement={statement!r} reason={type(exc).__name__}")

    async def execute_sql(
        self,
        sql: str,
        max_rows: int | None = None,
        timeout_seconds: int | None = None,
    ) -> QueryExecutionResult:
        effective_max_rows = max_rows or app_config.agent.max_result_rows
        effective_timeout = timeout_seconds or app_config.agent.query_timeout_seconds
        if effective_max_rows <= 0:
            raise ValueError("max_rows must be greater than 0")

        started_at = time.perf_counter()
        try:
            await self._best_effort_readonly_session(effective_timeout)
            result = await self.session.execute(text(sql))
            fetched = result.mappings().fetchmany(effective_max_rows + 1)
            truncated = len(fetched) > effective_max_rows
            rows = [dict(row) for row in fetched[:effective_max_rows]]
            return QueryExecutionResult(
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                execution_time_ms=int((time.perf_counter() - started_at) * 1000),
            )
        except asyncio.CancelledError:
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise
        else:
            await self.session.rollback()
        finally:
            if self.session.in_transaction():
                await self.session.rollback()
