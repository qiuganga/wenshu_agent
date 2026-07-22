from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.llm.gateway import llm_gateway as llm
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant


async def recall_column(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "recall_column", "message": "Recalling columns"})

    query = state["query"]
    keywords = state.get("keywords", [])
    embedding_client = runtime.context["embedding_client"]
    repository = runtime.context["column_qdrant_repository"]

    expanded_keywords = await llm.ainvoke_json("extend_keywords_for_column_recall", {"query": query})
    if not isinstance(expanded_keywords, list):
        expanded_keywords = []

    retrieved_map: dict[str, ColumnInfoQdrant] = {}
    for keyword in list(dict.fromkeys(keywords + [str(value) for value in expanded_keywords])):
        embedding = await embedding_client.aembed_query(keyword)
        payloads: list[ColumnInfoQdrant] = await repository.search(embedding)
        for payload in payloads:
            retrieved_map.setdefault(payload["id"], payload)

    retrieved = list(retrieved_map.values())
    logger.info(f"recall column count={len(retrieved)}")
    return {"retrieved_columns": retrieved, "table_candidates": retrieved}
