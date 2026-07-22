from app.security.policy import PolicyRule


def test_policy_rule_serializes_and_matches_conditions():
    rule = PolicyRule(
        resource="table:sales",
        action="read",
        condition={"department": "finance"},
        description="finance table",
    )
    loaded = PolicyRule.from_dict(rule.to_dict())

    assert loaded == rule
    assert loaded.matches(resource="table:sales", action="read", attributes={"department": "finance"})
    assert not loaded.matches(resource="table:sales", action="read", attributes={"department": "ops"})


def test_policy_rule_supports_wildcard():
    rule = PolicyRule(resource="table:*", action="read")

    assert not rule.matches(resource="table:sales", action="read")
