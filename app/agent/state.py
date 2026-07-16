from typing import TypedDict

from app.models.es.value_info_es import ValueInfoES
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant


class ColumnInfoState(TypedDict):
    name: str
    type: str
    role: str
    examples: list
    description: str
    alias: list[str]


class TableInfoState(TypedDict):
    name: str
    role: str
    description: str
    columns: list[ColumnInfoState]


class MetricInfoState(TypedDict):
    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]


class DateInfoState(TypedDict):
    date: str
    weekday: str
    quarter: str


class DBInfoState(TypedDict):
    dialect: str
    version: str


class DataAgentState(TypedDict):
    query: str  # 用户查询
    keywords: list[str]  # 用户查询的关键字

    retrieved_columns: list[ColumnInfoQdrant]  # 召回的字段信息
    retrieved_values: list[ValueInfoES]  # 召回的值信息
    retrieved_metrics: list[MetricInfoQdrant]  # 召回的指标信息

    table_infos: list[TableInfoState]  # 表信息
    metric_infos: list[MetricInfoState]  # 指标信息

    date_info: DateInfoState  # 日期信息
    db_info: DBInfoState  # 数据库信息

    sql: str  # 生成的SQL

    error: str  # 验证SQL时的错误信息

    result: list[dict]  # 执行SQL的结果
    interpretation: str  # 对结果的自然语言解读
