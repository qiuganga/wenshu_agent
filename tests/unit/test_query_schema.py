import pytest
from pydantic import ValidationError

from app.api.schemas.query_schema import QueryRequest
from app.config.app_config import app_config


@pytest.mark.parametrize("query", ["", "   "])
def test_blank_query_rejected(query):
    with pytest.raises(ValidationError):
        QueryRequest(query=query)


def test_too_long_query_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(query="x" * 2001)


def test_max_rows_cannot_exceed_global_config():
    with pytest.raises(ValidationError):
        QueryRequest(query="hello", max_rows=app_config.agent.max_result_rows + 1)


def test_conversation_id_validation():
    assert QueryRequest(query="hello", conversation_id="abc-123").conversation_id == "abc-123"
    with pytest.raises(ValidationError):
        QueryRequest(query="hello", conversation_id="??")
