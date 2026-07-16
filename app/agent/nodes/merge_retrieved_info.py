from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState, TableInfoState, MetricInfoState, ColumnInfoState
from app.core.logging import logger
from app.models.mysql.column_info_mysql import ColumnInfoMySQL
from app.models.mysql.table_info_mysql import TableInfoMySQL
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant


async def merge_retrieved_info(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"stage": "合并召回信息"})

    # 已召回信息
    retrieved_columns = state["retrieved_columns"]
    retrieved_values = state["retrieved_values"]
    retrieved_metrics = state["retrieved_metrics"]

    # 合并目标
    table_infos: list[TableInfoState] = []
    metric_infos: list[MetricInfoState] = []

    # 获取所需依赖
    meta_mysql_repository = runtime.context["meta_mysql_repository"]

    retrieved_columns_map: dict[str, ColumnInfoQdrant] = {retrieved_column["id"]: retrieved_column for retrieved_column
                                                          in retrieved_columns}
    try:
        # 将指标信息的相关字段加入字段信息列表
        for retrieved_metric in retrieved_metrics:
            relevant_columns = retrieved_metric["relevant_columns"]
            for relevant_column in relevant_columns:
                if relevant_column not in retrieved_columns_map:
                    column_info_mysql: ColumnInfoMySQL = await meta_mysql_repository.get_column_info_by_id(
                        relevant_column)
                    retrieved_columns_map[relevant_column] = convert_column_info_from_mysql_to_qdrant(column_info_mysql)

        # 将字段取值合并到字段信息列表
        for retrieved_value in retrieved_values:
            column_id = retrieved_value["column_id"]
            column_value = retrieved_value["value"]
            #
            if column_id not in retrieved_columns_map:
                column_info_mysql: ColumnInfoMySQL = await meta_mysql_repository.get_column_info_by_id(column_id)
                retrieved_columns_map[column_id] = convert_column_info_from_mysql_to_qdrant(column_info_mysql)
            if column_value not in retrieved_columns_map[column_id]["examples"]:
                retrieved_columns_map[column_id]["examples"].append(column_value)

        # 将字段信息按照所属表整理，得到最终的table_infos: list[TableInfoState]
        # 按照字段所属的table_id分组，得到table_id->columns映射
        table_to_columns_map: dict[str, list[ColumnInfoQdrant]] = {}
        for column in retrieved_columns_map.values():
            table_id = column["table_id"]
            if table_id not in table_to_columns_map:
                table_to_columns_map[table_id] = []
            table_to_columns_map[table_id].append(column)

        # 显式添加每个表的主外键信息
        for table_id in table_to_columns_map.keys():
            # 查询主外键字段
            key_columns: list[ColumnInfoMySQL] = await meta_mysql_repository.get_key_columns_by_table_id(table_id)

            # 当前表已有的所有列ID
            column_ids = [column["id"] for column in table_to_columns_map[table_id]]

            for key_column in key_columns:
                if key_column.id not in column_ids:
                    table_to_columns_map[table_id].append(convert_column_info_from_mysql_to_qdrant(key_column))

        # 将table_id->columns映射转换为table_infos: list[TableInfoState]
        for table_id, columns in table_to_columns_map.items():
            table: TableInfoMySQL = await  meta_mysql_repository.get_table_info_by_id(table_id)
            columns = [convert_column_info_from_qdrant_to_state(column) for column in columns]
            table_info_state = TableInfoState(name=table.name,
                                              role=table.role,
                                              description=table.description,
                                              columns=columns)
            table_infos.append(table_info_state)

        # 处理指标信息
        metric_infos = [convert_metric_info_from_qdrant_to_state(metric_info_qdrant) for metric_info_qdrant in
                        retrieved_metrics]

        logger.info(
            f"合并召回信息: 表信息-{[table_info['name'] for table_info in table_infos]},指标信息-{[metric_info['name'] for metric_info in metric_infos]}")
        return {"table_infos": table_infos, "metric_infos": metric_infos}
    except Exception as e:
        logger.error(f"合并召回信息失败: {str(e)}")
        raise


def convert_metric_info_from_qdrant_to_state(metric_info_qdrant: MetricInfoQdrant) -> MetricInfoState:
    return MetricInfoState(
        name=metric_info_qdrant["name"],
        description=metric_info_qdrant["description"],
        relevant_columns=metric_info_qdrant["relevant_columns"],
        alias=metric_info_qdrant["alias"]
    )


def convert_column_info_from_qdrant_to_state(column_info_qdrant: ColumnInfoQdrant) -> ColumnInfoState:
    return ColumnInfoState(
        name=column_info_qdrant["name"],
        type=column_info_qdrant["type"],
        role=column_info_qdrant["role"],
        examples=column_info_qdrant["examples"],
        description=column_info_qdrant["description"],
        alias=column_info_qdrant["alias"]
    )


def convert_column_info_from_mysql_to_qdrant(column_info_mysql: ColumnInfoMySQL) -> ColumnInfoQdrant:
    return ColumnInfoQdrant(
        id=column_info_mysql.id,
        name=column_info_mysql.name,
        type=column_info_mysql.type,
        role=column_info_mysql.role,
        examples=column_info_mysql.examples,
        description=column_info_mysql.description,
        alias=column_info_mysql.alias,
        table_id=column_info_mysql.table_id
    )

