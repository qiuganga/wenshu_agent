import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes._result_summary import summarize_result
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


async def interpret_result(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"stage": "结果解读"})

    query = state["query"]
    sql = state["sql"]
    result = state["result"]

    # 空结果短路，不调用 LLM
    if not result:
        interpretation = "未查询到符合条件的数据。"
        writer({"interpretation_delta": interpretation})
        return {"interpretation": interpretation}

    try:
        summary = summarize_result(result)

        prompt = PromptTemplate(template=load_prompt("interpret_result"),
                                input_variables=["query", "sql", "summary"])
        output_parser = StrOutputParser()

        chain = prompt | llm | output_parser

        chunks = []
        async for token in chain.astream(
                {"query": query,
                 "sql": sql,
                 "summary": yaml.dump(summary, allow_unicode=True, sort_keys=False)}):
            chunks.append(token)
            writer({"interpretation_delta": token})

        interpretation = "".join(chunks)
        logger.info(f"结果解读: {interpretation}")
        return {"interpretation": interpretation}
    except Exception as e:
        # 结果数据此时已推送给前端，解读失败只做降级提示，不中断整个请求
        logger.error(f"结果解读失败: {str(e)}")
        fallback = "结果解读生成失败，请直接查看查询结果。"
        writer({"interpretation_delta": fallback})
        return {"interpretation": fallback}
