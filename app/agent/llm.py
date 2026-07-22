from typing import Any

from app.llm.gateway import llm_gateway
from app.llm.model_router import MissingLLM, model_router


def create_llm() -> Any:
    return model_router.create_client(model_router.route().model_name)


llm: Any = llm_gateway

__all__ = ["MissingLLM", "create_llm", "llm"]
