import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


def _strip_code_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lower().startswith("sql"):
            value = value[3:]
    return value.strip()


async def generate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "generate_sql", "message": "Generating SQL"})

    prompt = PromptTemplate(
        template=load_prompt("generate_sql"),
        input_variables=["query", "query_plan", "table_infos", "metric_infos", "date_info", "db_info"],
    )
    chain = prompt | llm | StrOutputParser()
    sql = await chain.ainvoke(
        {
            "query": state["query"],
            "query_plan": yaml.dump(state.get("query_plan", {}), allow_unicode=True, sort_keys=False),
            "table_infos": yaml.dump(state.get("table_infos", []), allow_unicode=True, sort_keys=False),
            "metric_infos": yaml.dump(state.get("metric_infos", []), allow_unicode=True, sort_keys=False),
            "date_info": yaml.dump(state.get("date_info", {}), allow_unicode=True, sort_keys=False),
            "db_info": yaml.dump(state.get("db_info", {}), allow_unicode=True, sort_keys=False),
        }
    )
    sql = _strip_code_fence(sql)
    logger.info(f"sql generated length={len(sql)}")
    writer(
        {
            "event": "sql_generated",
            "node": "generate_sql",
            "message": "SQL generated",
            "sql_length": len(sql),
        }
    )
    return {"sql": sql, "error": None, "error_code": None}
