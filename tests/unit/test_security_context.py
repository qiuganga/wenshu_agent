from app.security.context import create_security_context


def test_security_context_created_with_safe_defaults_and_trace_linkage():
    context = create_security_context(
        user_id="alice",
        tenant_id="tenant-a",
        request_id="req-1",
        trace_id="trace-1",
    )

    assert context.user_id == "alice"
    assert context.tenant_or_default == "tenant-a"
    assert "agent:execute" in context.permissions
    assert context.request_id == "req-1"
    assert context.trace_id == "trace-1"


def test_security_context_safe_snapshot_hashes_user_id():
    context = create_security_context(user_id="alice")
    snapshot = context.to_safe_dict()

    assert snapshot["user_hash"] == context.user_hash
    assert "user_id" not in snapshot
    assert snapshot["tenant_id"] == "default"
