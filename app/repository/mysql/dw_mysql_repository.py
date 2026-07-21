from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app_config import app_config
from app.core.logging import logger
from app.security.sql_identifiers import quote_mysql_identifier, quote_mysql_qualified_identifier, safe_limit


class QueryExecutionResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: int = 0


class DWMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        safe_table = quote_mysql_qualified_identifier(table_name)
        result = await self.session.execute(text(f"show columns from {safe_table}"))
        return {row.Field: row.Type for row in result.fetchall()}

    async def get_column_values(self, table_name: str, column_name: str, limit: int):
        safe_table = quote_mysql_qualified_identifier(table_name)
        safe_column = quote_mysql_identifier(column_name)
        bounded_limit = safe_limit(limit)
        result = await self.session.execute(
            text(f"select distinct {safe_column} from {safe_table} limit {bounded_limit}")
        )
        return result.scalars().fetchall()

    async def get_db_info(self):
        result = await self.session.execute(text("select version()"))
        version = result.scalar()
        dialect = self.session.get_bind().dialect.name
        return {"version": version, "dialect": dialect}

    async def validate_sql(self, sql: str):
        await self.session.execute(text(f"explain {sql}"))

    async def _invalidate_session(self) -> None:
        invalidate = getattr(self.session, "invalidate", None)
        if callable(invalidate):
            result = invalidate()
            if inspect.isawaitable(result):
                await result
            return
        await self.session.rollback()

    async def _best_effort_statement_timeout(self, timeout_seconds: float) -> None:
        timeout_ms = max(1, int(timeout_seconds * 1000))
        try:
            await self.session.execute(text(f"SET SESSION MAX_EXECUTION_TIME={timeout_ms}"))
        except Exception as exc:  # pragma: no cover - depends on database flavor and permissions
            logger.warning(f"statement timeout setup skipped reason={type(exc).__name__}")

    async def explain_json(self, sql: str, timeout_seconds: float | None = None) -> str:
        effective_timeout = timeout_seconds or app_config.agent.explain_timeout_seconds
        try:
            await self._best_effort_statement_timeout(effective_timeout)
            result = await self.session.execute(text(f"explain format=json {sql}"))
            value = result.scalar()
            return str(value or "{}")
        except asyncio.CancelledError:
            await self._invalidate_session()
            raise
        except TimeoutError:
            await self._invalidate_session()
            raise
        except Exception:
            await self.session.rollback()
            raise
        finally:
            if self.session.in_transaction():
                await self.session.rollback()

    async def _best_effort_readonly_session(self, timeout_seconds: float) -> None:
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
        timeout_seconds: float | None = None,
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
            await self._invalidate_session()
            raise
        except TimeoutError:
            await self._invalidate_session()
            raise
        except Exception:
            await self.session.rollback()
            raise
        else:
            await self.session.rollback()
        finally:
            if self.session.in_transaction():
                await self.session.rollback()
