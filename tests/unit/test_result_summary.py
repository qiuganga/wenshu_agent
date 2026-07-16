from app.agent.nodes._result_summary import summarize_result


def test_summary_empty_result():
    summary = summarize_result([])
    assert summary["row_count"] == 0
    assert summary["columns"] == []


def test_summary_numeric_stats():
    summary = summarize_result([{"region": "??", "amount": 10}, {"region": "??", "amount": 30}])
    assert summary["row_count"] == 2
    assert summary["numeric_stats"]["amount"]["sum"] == 40
    assert summary["numeric_stats"]["amount"]["avg"] == 20


def test_summary_truncated():
    summary = summarize_result([{"x": i} for i in range(60)], sample_n=50)
    assert summary["truncated"] is True
    assert len(summary["sample"]) == 50


def test_summary_masks_sample():
    summary = summarize_result([{"mobile": "13812345678", "amount": 10}], sample_n=20)
    assert summary["sample"] == [{"mobile": "138****5678", "amount": 10}]
