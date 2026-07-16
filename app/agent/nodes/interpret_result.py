import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


async def interpret_result(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "interpret_result", "message": "Interpreting result"})

    summary = state.get("result_summary", {})
    if not state.get("result"):
        interpretation = "未查询到符合条件的数据。"
        writer(
            {
                "event": "result",
                "node": "interpret_result",
                "message": "Result interpreted",
                "answer_delta": interpretation,
            }
        )
        return {"interpretation": interpretation, "final_answer": interpretation}

    prompt = PromptTemplate(template=load_prompt("interpret_result"), input_variables=["query", "sql", "summary"])
    chain = prompt | llm | StrOutputParser()

    chunks: list[str] = []
    async for token in chain.astream(
        {
            "query": state["query"],
            "sql": state.get("normalized_sql") or state.get("sql", ""),
            "summary": yaml.dump(summary, allow_unicode=True, sort_keys=False),
        }
    ):
        chunks.append(token)
        writer({"event": "result", "node": "interpret_result", "message": "Interpreting result", "answer_delta": token})

    interpretation = "".join(chunks)
    logger.info(f"result interpreted chars={len(interpretation)}")
    return {"interpretation": interpretation, "final_answer": interpretation}
