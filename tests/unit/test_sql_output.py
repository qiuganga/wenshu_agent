import pytest

from app.agent.nodes._sql_output import parse_sql_generation_output, validate_generated_sql
from app.core.exceptions import SQLValidationError


def test_parse_sql_generation_json():
    parsed = parse_sql_generation_output('{"sql":"select order_id from fact_order"}')
    assert parsed.sql == "select order_id from fact_order"


@pytest.mark.parametrize("text", ["select * from t", "{}", '{"sql":""}'])
def test_parse_invalid_sql_output_rejected(text):
    with pytest.raises(SQLValidationError):
        validate_generated_sql(parse_sql_generation_output(text))


def test_explanatory_output_rejected():
    with pytest.raises(SQLValidationError):
        validate_generated_sql(parse_sql_generation_output('{"sql":"SQL: select order_id from fact_order"}'))
