import asyncio

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.logging import logger


async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"stage": "验证SQL"})

    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    sql = state["sql"]

    try:
        await dw_mysql_repository.validate_sql(sql)
        logger.info(f"SQL验证成功: {sql}")
        return {"error": None}
    except Exception as e:
        logger.error(f"SQL验证失败: {sql}")
        return {"error": str(e)}

