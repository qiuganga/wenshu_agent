from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import ColumnInfoState, DataAgentState, MetricInfoState, TableInfoState
from app.core.logging import logger
from app.models.mysql.column_info_mysql import ColumnInfoMySQL
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant


async def merge_retrieved_info(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "merge_retrieved_info", "message": "Merging recalled metadata"})

    retrieved_columns = state.get("retrieved_columns", [])
    retrieved_values = state.get("retrieved_values", [])
    retrieved_metrics = state.get("retrieved_metrics", [])
    meta_mysql_repository = runtime.context["meta_mysql_repository"]

    retrieved_columns_map: dict[str, ColumnInfoQdrant] = {
        retrieved_column["id"]: retrieved_column for retrieved_column in retrieved_columns
    }

    for retrieved_metric in retrieved_metrics:
        for relevant_column in retrieved_metric["relevant_columns"]:
            if relevant_column not in retrieved_columns_map:
                column_info_mysql = await meta_mysql_repository.get_column_info_by_id(relevant_column)
                if column_info_mysql is not None:
                    retrieved_columns_map[relevant_column] = convert_column_info_from_mysql_to_qdrant(column_info_mysql)

    for retrieved_value in retrieved_values:
        column_id = retrieved_value["column_id"]
        column_value = retrieved_value["value"]
        if column_id not in retrieved_columns_map:
            column_info_mysql = await meta_mysql_repository.get_column_info_by_id(column_id)
            if column_info_mysql is None:
                continue
            retrieved_columns_map[column_id] = convert_column_info_from_mysql_to_qdrant(column_info_mysql)
        if column_value not in retrieved_columns_map[column_id]["examples"]:
            retrieved_columns_map[column_id]["examples"].append(column_value)

    table_to_columns_map: dict[str, list[ColumnInfoQdrant]] = {}
    for column in retrieved_columns_map.values():
        table_to_columns_map.setdefault(column["table_id"], []).append(column)

    for table_id, columns in table_to_columns_map.items():
        column_ids = {column["id"] for column in columns}
        key_columns: list[ColumnInfoMySQL] = await meta_mysql_repository.get_key_columns_by_table_id(table_id)
        for key_column in key_columns:
            if key_column.id not in column_ids:
                columns.append(convert_column_info_from_mysql_to_qdrant(key_column))

    table_infos: list[TableInfoState] = []
    for table_id, columns in table_to_columns_map.items():
        table = await meta_mysql_repository.get_table_info_by_id(table_id)
        if table is None:
            continue
        table_infos.append(
            TableInfoState(
                name=table.name,
                role=table.role,
                description=table.description,
                columns=[convert_column_info_from_qdrant_to_state(column) for column in columns],
            )
        )

    metric_infos = [convert_metric_info_from_qdrant_to_state(metric) for metric in retrieved_metrics]
    logger.info(f"metadata merged table_count={len(table_infos)} metric_count={len(metric_infos)}")
    return {"table_infos": table_infos, "metric_infos": metric_infos}


def convert_metric_info_from_qdrant_to_state(metric_info_qdrant: MetricInfoQdrant) -> MetricInfoState:
    return MetricInfoState(
        name=metric_info_qdrant["name"],
        description=metric_info_qdrant["description"],
        relevant_columns=metric_info_qdrant["relevant_columns"],
        alias=metric_info_qdrant["alias"],
    )


def convert_column_info_from_qdrant_to_state(column_info_qdrant: ColumnInfoQdrant) -> ColumnInfoState:
    return ColumnInfoState(
        name=column_info_qdrant["name"],
        type=column_info_qdrant["type"],
        role=column_info_qdrant["role"],
        examples=column_info_qdrant["examples"],
        description=column_info_qdrant["description"],
        alias=column_info_qdrant["alias"],
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
        table_id=column_info_mysql.table_id,
    )
