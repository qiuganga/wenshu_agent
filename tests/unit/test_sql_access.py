from app.security.context import create_security_context
from app.security.sql_access import SQLAccessCheck, SQLAccessController


def test_sql_access_allows_table_and_column_read():
    context = create_security_context(user_id="u1", permissions=["table:read", "column:read"])
    controller = SQLAccessController()

    result = controller.check(
        context,
        SQLAccessCheck(operation="SELECT", tables=["sales"], columns={"sales": ["amount"]}),
    )

    assert result.allowed is True


def test_sql_access_denies_table_without_permission():
    context = create_security_context(user_id="u1", permissions=["column:read"])
    controller = SQLAccessController()

    result = controller.check(context, SQLAccessCheck(operation="SELECT", tables=["sales"]))

    assert result.allowed is False
    assert result.permission_decision == "DENY"


def test_sql_access_denies_write_operations_by_default():
    context = create_security_context(user_id="u1", permissions=["table:read"])
    controller = SQLAccessController()

    result = controller.check(context, SQLAccessCheck(operation="UPDATE", tables=["sales"]))

    assert result.allowed is False
    assert result.denied_reason == "write_operations_are_not_allowed"
