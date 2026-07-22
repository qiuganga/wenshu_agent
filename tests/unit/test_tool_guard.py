from app.security.context import create_security_context
from app.security.tool_guard import ToolMetadata, ToolPermissionGuard


def test_tool_guard_allows_authorized_tool():
    context = create_security_context(user_id="u1", permissions=["tool:search:execute"])
    guard = ToolPermissionGuard()

    decision = guard.check(context, ToolMetadata(name="search", risk_level="LOW"))

    assert decision.allowed is True


def test_tool_guard_denies_unauthorized_tool():
    context = create_security_context(user_id="u1", permissions=[])
    guard = ToolPermissionGuard()

    decision = guard.check(context, ToolMetadata(name="search", risk_level="LOW"))

    assert decision.allowed is False


def test_high_risk_tool_requires_explicit_permission():
    context = create_security_context(user_id="u1", permissions=["tool:execute"])
    guard = ToolPermissionGuard()

    decision = guard.check(context, ToolMetadata(name="export_data", risk_level="HIGH"))

    assert decision.allowed is False
    assert decision.reason == "high_risk_tool_requires_explicit_permission"
