from app.security.authorization import AuthorizationEngine
from app.security.context import create_security_context
from app.security.policy import PolicyRule


def test_authorization_allows_explicit_permission():
    engine = AuthorizationEngine()
    context = create_security_context(user_id="u1", permissions=["table:sales:read"])

    decision = engine.authorize(context, resource="table:sales", action="read")

    assert decision.allowed is True
    assert decision.decision == "ALLOW"


def test_authorization_default_denies_missing_permission():
    engine = AuthorizationEngine()
    context = create_security_context(user_id="u1", permissions=[])

    decision = engine.authorize(context, resource="table:sales", action="read")

    assert decision.allowed is False
    assert decision.reason == "default_deny"


def test_authorization_uses_role_and_abac_policy():
    engine = AuthorizationEngine(
        role_permissions={"analyst": {"agent:execute"}},
        policy_rules=[
            PolicyRule(
                resource="table:sales",
                action="read",
                effect="allow",
                condition={"department": "finance"},
            )
        ],
    )
    context = create_security_context(user_id="u1", roles=["analyst"], permissions=[])

    assert engine.authorize(context, resource="agent", action="execute").allowed is True
    assert (
        engine.authorize(
            context,
            resource="table:sales",
            action="read",
            attributes={"department": "finance"},
        ).allowed
        is True
    )
    assert (
        engine.authorize(
            context,
            resource="table:sales",
            action="read",
            attributes={"department": "sales"},
        ).allowed
        is False
    )
