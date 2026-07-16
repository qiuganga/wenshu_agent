from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config.app_config import app_config


class MissingLLM:
    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("llm.api_key is not configured; configure conf/app_config.yaml before calling the LLM")


def create_llm() -> ChatOpenAI | MissingLLM:
    if not app_config.llm.api_key.strip():
        return MissingLLM()
    return ChatOpenAI(
        model=app_config.llm.model_name,
        api_key=SecretStr(app_config.llm.api_key),
        base_url=app_config.llm.base_url,
        temperature=app_config.llm.temperature,
        timeout=app_config.llm.timeout_seconds,
        max_retries=app_config.llm.max_retries,
    )


llm: Any = create_llm()
