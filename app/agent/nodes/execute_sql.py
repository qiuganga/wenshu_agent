import asyncio

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.logging import logger


async def execute_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"stage": "执行SQL"})

    sql = state["sql"]

    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    try:
        result = await dw_mysql_repository.execute_sql(sql)

        writer({"result": result})
        logger.info(f"执行SQL结果: {result}")

        return {"result": result}

    except Exception as e:
        logger.error(f"执行SQL失败:{str(e)}")
        raise

