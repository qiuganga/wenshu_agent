from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config.app_config import app_config


class MissingLLM:
    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("llm.api_key is not configured; configure conf/app_config.yaml before calling the LLM")


@dataclass(frozen=True)
class ModelRoute:
    model_name: str
    fallback_used: bool = False


class ModelRouter:
    def __init__(self) -> None:
        self.primary_model = app_config.llm.default_model or app_config.llm.model_name
        self.fallback_model = app_config.llm.fallback_model

    def route(self, *, fallback: bool = False) -> ModelRoute:
        if fallback and self.fallback_model:
            return ModelRoute(model_name=self.fallback_model, fallback_used=True)
        return ModelRoute(model_name=self.primary_model, fallback_used=False)

    def create_client(self, model_name: str) -> Any:
        if not app_config.llm.api_key.strip():
            return MissingLLM()
        return ChatOpenAI(
            model=model_name,
            api_key=SecretStr(app_config.llm.api_key),
            base_url=app_config.llm.base_url,
            temperature=app_config.llm.temperature,
            timeout=app_config.llm.timeout_seconds,
            max_retries=0,
        )


model_router = ModelRouter()
