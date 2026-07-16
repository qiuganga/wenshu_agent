import pytest

from app.security.sql_identifiers import (
    IdentifierError,
    quote_mysql_identifier,
    quote_mysql_qualified_identifier,
    safe_limit,
)


def test_quote_valid_identifier():
    assert quote_mysql_identifier("fact_order") == "`fact_order`"
    assert quote_mysql_identifier("_id1") == "`_id1`"


def test_quote_schema_table():
    assert quote_mysql_qualified_identifier("dw.fact_order") == "`dw`.`fact_order`"


@pytest.mark.parametrize("value", ["x;drop", "bad name", "`x`", "x--", "??", "a.b.c", ""])
def test_reject_unsafe_identifier(value):
    with pytest.raises(IdentifierError):
        quote_mysql_qualified_identifier(value)


def test_safe_limit_bounds():
    assert safe_limit(10) == 10
    assert safe_limit(999999, max_limit=100) == 100
    with pytest.raises(IdentifierError):
        safe_limit(-1)
    with pytest.raises(IdentifierError):
        safe_limit("1")  # type: ignore[arg-type]
