import pytest

from app.core.exceptions import SQLSecurityError
from app.security.sql_security import ensure_select_limit, validate_readonly_sql

ALLOWED = {"fact_order", "dim_region"}


@pytest.mark.parametrize("sql", [
    "delete from fact_order",
    "update fact_order set order_amount = 1",
    "insert into fact_order(order_id) values (1)",
    "drop table fact_order",
    "alter table fact_order add column x int",
    "select * from fact_order; select * from dim_region",
])
def test_reject_unsafe_sql(sql):
    with pytest.raises(SQLSecurityError):
        validate_readonly_sql(sql, ALLOWED)


def test_accept_plain_select():
    result = validate_readonly_sql("select order_id from fact_order limit 10", ALLOWED)
    assert result.statement_type == "SELECT"
    assert result.referenced_tables == ["fact_order"]


def test_accept_with_select():
    result = validate_readonly_sql(
        "with t as (select order_id from fact_order limit 10) select * from t limit 5",
        ALLOWED,
    )
    assert result.statement_type == "SELECT"


def test_reject_unauthorized_table():
    with pytest.raises(SQLSecurityError):
        validate_readonly_sql("select * from secret_table", ALLOWED)


def test_ensure_limit_adds_limit():
    sql = ensure_select_limit("select * from fact_order", 200)
    assert "LIMIT 200" in sql.upper()


def test_ensure_limit_keeps_existing_limit():
    sql = ensure_select_limit("select * from fact_order limit 5", 200)
    assert "LIMIT 5" in sql.upper()
    assert "LIMIT 200" not in sql.upper()

