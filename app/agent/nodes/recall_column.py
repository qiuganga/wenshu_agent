import asyncio

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.clients.embedding_client_manager import embedding_client_manager
from app.core.logging import logger
from app.models.qdrant.column_info_qdrant import ColumnInfoQdrant
from app.prompt.prompt_loader import load_prompt


async def recall_column(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"stage": "召回字段"})

    query = state["query"]
    keywords = state["keywords"]

    embedding_client = runtime.context["embedding_client"]
    column_qdrant_repository = runtime.context["column_qdrant_repository"]

    try:
        # 使用LLM扩展关键词
        prompt = PromptTemplate(template=load_prompt("extend_keywords_for_column_recall"), input_variables=["query"])
        output_parser = JsonOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        # 使用扩展后的关键词召回字段信息
        retrieved_columns_map: dict[str, ColumnInfoQdrant] = {}

        keywords = list(set(keywords + result))
        for keyword in keywords:
            embedding = await embedding_client.aembed_query(keyword)
            payloads: list[ColumnInfoQdrant] = await column_qdrant_repository.search(embedding)
            for payload in payloads:
                column_id = payload["id"]
                if column_id not in retrieved_columns_map:
                    retrieved_columns_map[column_id] = payload

        retrieved_columns = list(retrieved_columns_map.values())

        logger.info(f"召回字段信息：{list(retrieved_columns_map.keys())}")
        return {"retrieved_columns": retrieved_columns}
    except Exception as e:
        logger.error(f"召回字段信息失败: {str(e)}")
        raise
