from app.governance.context_budget import ContextBudgetPolicy


def test_context_budget_limits_documents_and_removes_raw_result() -> None:
    policy = ContextBudgetPolicy(max_documents=1, max_document_chars=5)

    docs = policy.trim_documents(
        [
            {"content": "abcdef", "raw_result": "unsafe", "score": 1},
            {"content": "second"},
        ]
    )

    assert docs == [{"content": "abcde", "score": 1}]


def test_context_budget_limits_history_without_removing_roles() -> None:
    policy = ContextBudgetPolicy(max_history_messages=1, max_document_chars=4)

    assert policy.trim_history([{"role": "user", "content": "abcdef"}, {"role": "assistant", "content": "ghijk"}]) == [
        {"role": "assistant", "content": "ghij"}
    ]
