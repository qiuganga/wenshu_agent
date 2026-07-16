from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config.app_config import app_config


class QueryRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    conversation_id: str | None = None
    max_rows: int | None = Field(default=None, ge=1)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty")
        return stripped

    @model_validator(mode="after")
    def validate_max_rows(self):
        if self.max_rows is not None and self.max_rows > app_config.agent.max_result_rows:
            raise ValueError(f"max_rows must be <= {app_config.agent.max_result_rows}")
        return self


QuerySchema = QueryRequest
