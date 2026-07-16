import asyncio

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
    writer({"stage": "召回字段取值"})

    query = state["query"]
    keywords = state["keywords"]

    value_es_repository = runtime.context["value_es_repository"]

    try:
        # 使用LLM扩展关键词
        prompt = PromptTemplate(template=load_prompt("extend_keywords_for_value_recall"), input_variables=["query"])
        output_parser = JsonOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        # 使用扩展后的关键词召回字段取值
        values_map: dict[str, ValueInfoES] = {}
        keywords = list(set(keywords + result))
        for keyword in keywords:
            values: list[ValueInfoES] = await value_es_repository.search(keyword)
            for value in values:
                value_id = value["id"]
                if value_id not in values_map:
                    values_map[value_id] = value

        retrieved_values = list(values_map.values())
        logger.info(f"召回字段取值：{list(values_map.keys())}")

        return {'retrieved_values': retrieved_values}
    except Exception as e:
        logger.error(f"召回字段取值失败: {str(e)}")
        raise
