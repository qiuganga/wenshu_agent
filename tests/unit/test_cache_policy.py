from app.cache.policy import CachePolicy


def policy() -> CachePolicy:
    return CachePolicy(max_entry_bytes=1024, cache_safe_final_summary=True)


def test_cache_policy_allows_success_readonly_safe_payload():
    decision = policy().can_write(
        final_status="success",
        payload={"final_answer": "ok", "result_summary": {"row_count": 1}},
        metadata={"read_only": True, "data_version": "v1"},
    )

    assert decision.allowed is True


def test_cache_policy_blocks_failure_timeout_cancelled_and_unknown():
    for final_status in ["failed", "timeout", "cancelled"]:
        decision = policy().can_write(
            final_status=final_status,
            payload={"result_summary": {}},
            metadata={"read_only": True, "data_version": "v1"},
        )
        assert decision.allowed is False

    decision = policy().can_write(
        final_status="success",
        payload={"result_summary": {}},
        metadata={"read_only": True, "data_version": "v1", "execution_outcome_unknown": True},
    )
    assert decision.allowed is False


def test_cache_policy_blocks_sensitive_oversize_fallback_and_unknown_data_version():
    cache_policy = CachePolicy(max_entry_bytes=10, cache_safe_final_summary=True)

    assert (
        cache_policy.can_write(
            final_status="success",
            payload={"password": "secret"},
            metadata={"read_only": True, "data_version": "v1"},
        ).allowed
        is False
    )
    assert (
        cache_policy.can_write(
            final_status="success",
            payload={"result_summary": "x" * 100},
            metadata={"read_only": True, "data_version": "v1"},
        ).allowed
        is False
    )
    assert (
        policy()
        .can_write(
            final_status="success",
            payload={"result_summary": {}},
            metadata={"read_only": True, "data_version": ""},
        )
        .allowed
        is False
    )
    assert (
        policy()
        .can_write(
            final_status="success",
            payload={"result_summary": {}},
            metadata={"read_only": True, "data_version": "v1", "fallback_used": True},
        )
        .allowed
        is False
    )


def test_cache_policy_blocks_final_answer_when_disabled():
    decision = CachePolicy(max_entry_bytes=1024, cache_safe_final_summary=False).can_write(
        final_status="success",
        payload={"final_answer": "ok", "result_summary": {}},
        metadata={"read_only": True, "data_version": "v1"},
    )

    assert decision.allowed is False
