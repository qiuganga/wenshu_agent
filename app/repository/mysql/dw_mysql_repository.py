from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app_config import app_config


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

    async def execute_sql(self, sql: str):
        result = await self.session.execute(text(sql))
        rows = result.mappings().fetchmany(app_config.agent.max_result_rows)
        return [dict(row) for row in rows]

