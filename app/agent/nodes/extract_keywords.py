import jieba.analyse
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.logging import logger


async def extract_keywords(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"event": "stage", "node": "extract_keywords", "message": "Extracting keywords"})

    query = state["query"]
    keywords = jieba.analyse.extract_tags(query)
    keywords.append(query)
    keywords = list(dict.fromkeys(keywords))
    logger.info(f"keywords extracted count={len(keywords)}")
    return {"keywords": keywords, "normalized_query": query.strip()}
