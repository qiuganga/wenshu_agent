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
    writer({"stage": "召回指标"})

    query = state["query"]
    keywords = state["keywords"]

    embedding_client = runtime.context['embedding_client']
    metric_qdrant_repository = runtime.context['metric_qdrant_repository']

    try:
        # 使用LLM扩展关键词
        prompt = PromptTemplate(template=load_prompt("extend_keywords_for_metric_recall"), input_variables=["query"])
        output_parser = JsonOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        # 使用扩展后的关键词召回指标信息
        retrieved_metrics_map: dict[str, MetricInfoQdrant] = {}

        keywords = list(set(keywords + result))
        for keyword in keywords:
            embedding = await embedding_client.aembed_query(keyword)
            payloads: list[MetricInfoQdrant] = await metric_qdrant_repository.search(embedding)
            for payload in payloads:
                metric_id = payload["id"]
                if metric_id not in retrieved_metrics_map:
                    retrieved_metrics_map[metric_id] = payload

        retrieved_metrics = list(retrieved_metrics_map.values())

        logger.info(f"召回指标信息：{list(retrieved_metrics_map.keys())}")
        return {"retrieved_metrics": retrieved_metrics}
    except Exception as e:
        logger.error(f"召回指标信息失败: {str(e)}")
        raise
