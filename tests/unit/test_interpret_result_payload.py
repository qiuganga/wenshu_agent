from app.agent.nodes.interpret_result import _final_payload
from app.config.app_config import app_config


def test_final_payload_default_excludes_sql_and_raw_rows(monkeypatch):
    monkeypatch.setattr(app_config.agent, "expose_sql_to_client", False)
    monkeypatch.setattr(app_config.agent, "expose_raw_rows_to_client", False)
    payload = _final_payload(
        {
            "normalized_sql": "select phone from user",
            "result": [{"mobile": "13812345678"}],
            "result_summary": {"row_count": 1},
        },
        "ok",
    )
    assert payload == {"final_answer": "ok", "result_summary": {"row_count": 1}}


def test_final_payload_preserves_split_truncation_summary(monkeypatch):
    monkeypatch.setattr(app_config.agent, "expose_sql_to_client", False)
    monkeypatch.setattr(app_config.agent, "expose_raw_rows_to_client", False)
    result_summary = {
        "row_count": 2,
        "query_result_truncated": False,
        "sample_truncated": True,
        "truncated": True,
    }
    payload = _final_payload({"result_summary": result_summary}, "ok")

    assert payload == {"final_answer": "ok", "result_summary": result_summary}


def test_final_payload_raw_rows_are_capped_and_masked(monkeypatch):
    monkeypatch.setattr(app_config.agent, "expose_raw_rows_to_client", True)
    monkeypatch.setattr(app_config.agent, "result_sample_rows", 1)
    payload = _final_payload(
        {"result": [{"mobile": "13812345678"}, {"mobile": "13912345678"}], "result_summary": {}},
        "ok",
    )
    assert payload["rows"] == [{"mobile": "138****5678"}]
