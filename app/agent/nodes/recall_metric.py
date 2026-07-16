from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.models.qdrant.metric_info_qdrant import MetricInfoQdrant
from app.prompt.prompt_loader import load_prompt


async def recall_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "recall_metric", "message": "Recalling metrics"})

    query = state["query"]
    keywords = state.get("keywords", [])
    embedding_client = runtime.context["embedding_client"]
    metric_qdrant_repository = runtime.context["metric_qdrant_repository"]

    prompt = PromptTemplate(template=load_prompt("extend_keywords_for_metric_recall"), input_variables=["query"])
    chain = prompt | llm | JsonOutputParser()
    expanded_keywords = await chain.ainvoke({"query": query})

    retrieved_metrics_map: dict[str, MetricInfoQdrant] = {}
    for keyword in list(dict.fromkeys(keywords + expanded_keywords)):
        embedding = await embedding_client.aembed_query(keyword)
        payloads: list[MetricInfoQdrant] = await metric_qdrant_repository.search(embedding)
        for payload in payloads:
            retrieved_metrics_map.setdefault(payload["id"], payload)

    retrieved_metrics = list(retrieved_metrics_map.values())
    logger.info(f"metric recall count={len(retrieved_metrics)}")
    return {"retrieved_metrics": retrieved_metrics, "metric_candidates": retrieved_metrics}
