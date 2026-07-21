import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config.app_config import app_config

SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")


class QueryRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    conversation_id: str | None = None
    request_id: str | None = None
    user_id: str | None = None
    max_rows: int | None = Field(default=None, ge=1)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty")
        return stripped

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if not SAFE_ID_RE.match(stripped):
            raise ValueError("conversation_id contains invalid characters or is too long")
        return stripped

    @field_validator("request_id", "user_id")
    @classmethod
    def validate_safe_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if not SAFE_ID_RE.match(stripped):
            raise ValueError("identifier contains invalid characters or is too long")
        return stripped

    @model_validator(mode="after")
    def validate_max_rows(self):
        if self.max_rows is not None and self.max_rows > app_config.agent.max_result_rows:
            raise ValueError(f"max_rows must be <= {app_config.agent.max_result_rows}")
        return self


QuerySchema = QueryRequest
