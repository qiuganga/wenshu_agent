
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql.column_info_mysql import ColumnInfoMySQL
from app.models.mysql.column_metric_mysql import ColumnMetricMySQL
from app.models.mysql.metric_info_mysql import MetricInfoMySQL
from app.models.mysql.table_info_mysql import TableInfoMySQL


class MetaMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_table_infos(self, table_infos: list[TableInfoMySQL]):
        self.session.add_all(table_infos)

    async def save_column_infos(self, columns_info: list[ColumnInfoMySQL]):
        self.session.add_all(columns_info)

    async def save_metric_infos(self, metric_infos: list[MetricInfoMySQL]):
        self.session.add_all(metric_infos)

    async def save_column_metrics(self, column_metrics: list[ColumnMetricMySQL]):
        self.session.add_all(column_metrics)

    async def get_column_info_by_id(self, column_id: str) -> ColumnInfoMySQL | None:
        return await self.session.get(ColumnInfoMySQL, column_id)

    async def get_table_info_by_id(self, table_id: str) -> TableInfoMySQL | None:
        return await self.session.get(TableInfoMySQL, table_id)

    async def get_key_columns_by_table_id(self, table_id: str) -> list[ColumnInfoMySQL]:
        sql = """
            select * 
            from column_info 
            where table_id = :table_id 
            and role in ('primary_key', 'foreign_key')
        """
        query = select(ColumnInfoMySQL).from_statement(text(sql))
        result = await self.session.execute(query, {"table_id": table_id})
        return result.scalars().fetchall()