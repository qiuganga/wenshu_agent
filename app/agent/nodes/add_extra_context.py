from datetime import datetime

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState, DateInfoState
from app.core.logging import logger


async def add_extra_context(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "add_extra_context", "message": "Adding date and database context"})

    today = datetime.today()
    date_info = DateInfoState(
        date=today.strftime("%Y-%m-%d"),
        weekday=today.strftime("%A"),
        quarter=f"Q{(today.month - 1) // 3 + 1}",
    )
    db_info = await runtime.context["dw_mysql_repository"].get_db_info()
    logger.info(f"extra context added dialect={db_info.get('dialect')} version={db_info.get('version')}")
    return {"date_info": date_info, "db_info": db_info}
