from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.prompt.prompt_loader import load_prompt


async def recall_column(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "recall_column", "message": "Recalling table columns"})

    query = state["query"]
    keywords = state.get("keywords", [])
    embedding_client = runtime.context["embedding_client"]
    column_qdrant_repository = runtime.context["column_qdrant_repository"]

    prompt = PromptTemplate(template=load_prompt("extend_keywords_for_column_recall"), input_variables=["query"])
    chain = prompt | llm | JsonOutputParser()
    expanded_keywords = await chain.ainvoke({"query": query})

    retrieved_columns_map: dict[str, ColumnInfoQdrant] = {}
    for keyword in list(dict.fromkeys(keywords + expanded_keywords)):
        embedding = await embedding_client.aembed_query(keyword)
        payloads: list[ColumnInfoQdrant] = await column_qdrant_repository.search(embedding)
        for payload in payloads:
            retrieved_columns_map.setdefault(payload["id"], payload)

    retrieved_columns = list(retrieved_columns_map.values())
    logger.info(f"column recall count={len(retrieved_columns)}")
    return {"retrieved_columns": retrieved_columns, "table_candidates": retrieved_columns}
