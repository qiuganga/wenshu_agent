from typing import TypedDict


class ValueInfoES(TypedDict):
    id: str  # 值ID
    value: str  # 值
    type: str  # 值类型
    column_id: str  # 所属的字段ID
    column_name: str  # 所属的字段名称
    table_id: str  # 所属的表ID
    table_name: str  # 所属的表名称
