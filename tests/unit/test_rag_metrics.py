from app.evaluation.rag_metrics import evaluate_retrieval


def test_rag_metrics_recall_precision_and_relevance():
    scores = {metric.name: metric.score for metric in evaluate_retrieval(["doc1", "doc2"], ["doc1", "doc3"])}

    assert scores["retrieval_recall"] == 0.5
    assert scores["retrieval_precision"] == 0.5
    assert scores["context_relevance"] == 0.5


def test_rag_metrics_empty_expected_is_perfect_recall():
    scores = {metric.name: metric.score for metric in evaluate_retrieval([], [])}

    assert scores["retrieval_recall"] == 1.0
    assert scores["retrieval_precision"] == 1.0
