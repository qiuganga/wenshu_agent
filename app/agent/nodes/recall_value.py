from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.models.es.value_info_es import ValueInfoES
from app.prompt.prompt_loader import load_prompt


async def recall_value(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "recall_value", "message": "Recalling column values"})

    query = state["query"]
    keywords = state.get("keywords", [])
    value_es_repository = runtime.context["value_es_repository"]

    prompt = PromptTemplate(template=load_prompt("extend_keywords_for_value_recall"), input_variables=["query"])
    chain = prompt | llm | JsonOutputParser()
    expanded_keywords = await chain.ainvoke({"query": query})

    values_map: dict[str, ValueInfoES] = {}
    for keyword in list(dict.fromkeys(keywords + expanded_keywords)):
        values: list[ValueInfoES] = await value_es_repository.search(keyword)
        for value in values:
            values_map.setdefault(value["id"], value)

    retrieved_values = list(values_map.values())
    logger.info(f"value recall count={len(retrieved_values)}")
    return {"retrieved_values": retrieved_values}
