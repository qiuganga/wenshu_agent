from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.llm.gateway import llm_gateway as llm
from app.models.es.value_info_es import ValueInfoES


async def recall_value(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "recall_value", "message": "Recalling column values"})

    query = state["query"]
    keywords = state.get("keywords", [])
    value_es_repository = runtime.context["value_es_repository"]

    expanded_keywords = await llm.ainvoke_json("extend_keywords_for_value_recall", {"query": query})
    if not isinstance(expanded_keywords, list):
        expanded_keywords = []

    values_map: dict[str, ValueInfoES] = {}
    for keyword in list(dict.fromkeys(keywords + [str(value) for value in expanded_keywords])):
        values: list[ValueInfoES] = await value_es_repository.search(keyword)
        for value in values:
            values_map.setdefault(value["id"], value)

    retrieved_values = list(values_map.values())
    logger.info(f"value recall count={len(retrieved_values)}")
    return {"retrieved_values": retrieved_values}
