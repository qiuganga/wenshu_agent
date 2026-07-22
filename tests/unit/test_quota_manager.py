import pytest

from app.governance.common import GovernanceError
from app.governance.quota import QuotaManager, QuotaRule


def test_quota_manager_enforces_stricter_scope_and_uses_hash_keys() -> None:
    manager = QuotaManager("agent", [QuotaRule("requests", 1, 60)])

    manager.check_and_consume(user_id="alice", tenant_id="tenant-a")
    with pytest.raises(GovernanceError) as exc:
        manager.check_and_consume(user_id="alice", tenant_id="tenant-a")

    assert exc.value.error_code == "REQUEST_QUOTA_EXCEEDED"
    assert all("alice" not in key and "tenant-a" not in key for key in manager._local)


def test_quota_manager_isolates_scopes() -> None:
    manager = QuotaManager("agent", [QuotaRule("requests", 2, 60)])

    manager.check_and_consume(user_id="alice", tenant_id="tenant-a")
    manager.check_and_consume(user_id="bob", tenant_id="tenant-b")

    assert len(manager._local) == 5
