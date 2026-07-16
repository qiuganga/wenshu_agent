
from langchain_openai import ChatOpenAI

from app.config.app_config import app_config

llm = ChatOpenAI(
    model=app_config.llm.model_name,
    api_key=app_config.llm.api_key,
    base_url="https://api.siliconflow.cn/v1",
    temperature=0,
)

