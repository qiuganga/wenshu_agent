import pytest

from app.core.exceptions import SQLSecurityError
from app.security.sql_security import (
    build_sql_access_policy,
    enforce_select_limit,
    ensure_select_limit,
    validate_readonly_sql,
)

TABLE_INFOS = [
    {
        "name": "fact_order",
        "columns": [
            {"name": "order_id"},
            {"name": "region_id"},
            {"name": "order_amount"},
            {"name": "created_at"},
        ],
    },
    {"name": "dim_region", "columns": [{"name": "region_id"}, {"name": "region_name"}]},
]
ALLOWED, ALLOWED_COLUMNS = build_sql_access_policy(TABLE_INFOS)


@pytest.mark.parametrize(
    "sql",
    [
        "delete from fact_order",
        "update fact_order set order_amount = 1",
        "insert into fact_order(order_id) values (1)",
        "drop table fact_order",
        "alter table fact_order add column x int",
        "select order_id from fact_order; select region_id from dim_region",
        "select sleep(1) from fact_order",
        "select BENCHMARK(1000, md5('x')) from fact_order",
        "select load_file('/etc/passwd') from fact_order",
        "select get_lock('x', 1) from fact_order",
    ],
)
def test_reject_unsafe_sql(sql):
    with pytest.raises(SQLSecurityError):
        validate_readonly_sql(sql, ALLOWED, ALLOWED_COLUMNS)


def test_string_literal_and_column_named_sleep_are_allowed():
    validate_readonly_sql("select 'sleep' as name, order_id from fact_order limit 10", ALLOWED, ALLOWED_COLUMNS)


def test_accept_plain_select_with_columns():
    result = validate_readonly_sql("select order_id from fact_order limit 10", ALLOWED, ALLOWED_COLUMNS)
    assert result.statement_type == "SELECT"
    assert result.referenced_tables == ["fact_order"]
    assert result.referenced_columns == {"fact_order": ["order_id"]}


def test_accept_with_select_without_star():
    result = validate_readonly_sql(
        "with t as (select order_id from fact_order limit 10) select order_id from t limit 5",
        ALLOWED,
        ALLOWED_COLUMNS,
    )
    assert result.statement_type == "SELECT"


def test_reject_unauthorized_table():
    with pytest.raises(SQLSecurityError):
        validate_readonly_sql("select order_id from secret_table", ALLOWED, ALLOWED_COLUMNS)


def test_reject_unauthorized_column():
    with pytest.raises(SQLSecurityError):
        validate_readonly_sql("select secret_amount from fact_order", ALLOWED, ALLOWED_COLUMNS)


@pytest.mark.parametrize("sql", ["select * from fact_order", "select fact_order.* from fact_order"])
def test_reject_select_star(sql):
    with pytest.raises(SQLSecurityError):
        validate_readonly_sql(sql, ALLOWED, ALLOWED_COLUMNS)


def test_join_alias_and_aggregate_columns():
    result = validate_readonly_sql(
        """
        select r.region_name, sum(o.order_amount) as total
        from fact_order o join dim_region r on o.region_id = r.region_id
        group by r.region_name
        order by total desc
        limit 10
        """,
        ALLOWED,
        ALLOWED_COLUMNS,
    )
    assert result.referenced_columns["fact_order"] == ["order_amount", "region_id"]
    assert result.referenced_columns["dim_region"] == ["region_id", "region_name"]


def test_unqualified_single_table_column_passes():
    validate_readonly_sql("select order_amount from fact_order limit 10", ALLOWED, ALLOWED_COLUMNS)


def test_ambiguous_unqualified_column_rejected():
    with pytest.raises(SQLSecurityError):
        validate_readonly_sql(
            "select region_id from fact_order join dim_region on fact_order.region_id = dim_region.region_id",
            ALLOWED,
            ALLOWED_COLUMNS,
        )


def test_union_legal_columns():
    validate_readonly_sql(
        "select region_id from fact_order union select region_id from dim_region limit 10",
        ALLOWED,
        ALLOWED_COLUMNS,
    )


def test_ensure_limit_adds_limit():
    sql = ensure_select_limit("select order_id from fact_order", 200)
    assert "LIMIT 200" in sql.upper()


def test_enforce_limit_caps_existing_limit():
    sql = enforce_select_limit("select order_id from fact_order limit 1000000", 200)
    assert "LIMIT 200" in sql.upper()
    assert "1000000" not in sql


@pytest.mark.parametrize("limit", ["5", "200", "0"])
def test_enforce_limit_keeps_allowed_literal_limit(limit):
    sql = enforce_select_limit(f"select order_id from fact_order limit {limit}", 200)
    assert f"LIMIT {limit}" in sql.upper()


def test_enforce_limit_preserves_offset():
    sql = enforce_select_limit("select order_id from fact_order limit 10 offset 100", 200)
    assert "LIMIT 10" in sql.upper()
    assert "OFFSET 100" in sql.upper()


def test_enforce_limit_caps_union_outer_limit():
    sql = enforce_select_limit(
        "select order_id from fact_order union select region_id from dim_region limit 1000",
        200,
    )
    assert "LIMIT 200" in sql.upper()


def test_subquery_limit_does_not_satisfy_outer_limit():
    sql = enforce_select_limit("select order_id from (select order_id from fact_order limit 5) x", 200)
    assert sql.upper().count("LIMIT") == 2
    assert "LIMIT 200" in sql.upper()


@pytest.mark.parametrize("sql", ["select order_id from fact_order limit -1", "select order_id from fact_order limit ?"])
def test_illegal_limit_rejected(sql):
    with pytest.raises(SQLSecurityError):
        enforce_select_limit(sql, 200)


def test_max_rows_must_be_positive():
    with pytest.raises(SQLSecurityError):
        enforce_select_limit("select order_id from fact_order", 0)


def test_dangerous_words_in_literals_comments_and_aliases_are_not_rejected():
    validate_readonly_sql(
        "select 'prepare' as operation_name, order_id as execute_status from fact_order -- drop table x\nlimit 10",
        ALLOWED,
        ALLOWED_COLUMNS,
    )


@pytest.mark.parametrize(
    "sql",
    [
        "prepare stmt from 'select 1'",
        "execute stmt",
        "deallocate prepare stmt",
        "handler fact_order open",
        "load data infile 'x' into table fact_order",
        "select order_id from fact_order into outfile '/tmp/x'",
        "select order_id from fact_order into dumpfile '/tmp/x'",
        "select order_id from fact_order InTo   OutFile '/tmp/x'",
    ],
)
def test_reject_mysql_dangerous_capabilities(sql):
    with pytest.raises(SQLSecurityError):
        validate_readonly_sql(sql, ALLOWED, ALLOWED_COLUMNS)
