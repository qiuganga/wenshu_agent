from langchain_openai import ChatOpenAI

from app.config.app_config import app_config

llm = ChatOpenAI(
    model=app_config.llm.model_name,
    api_key=app_config.llm.api_key,
    base_url=app_config.llm.base_url,
    temperature=app_config.llm.temperature,
    timeout=app_config.llm.timeout_seconds,
    max_retries=app_config.llm.max_retries,
)
