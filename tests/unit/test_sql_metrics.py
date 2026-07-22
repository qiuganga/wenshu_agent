from app.evaluation.sql_metrics import SQLEvaluationInput, evaluate_sql


def scores(metrics):
    return {metric.name: metric.score for metric in metrics}


def test_sql_metrics_use_ast_for_table_and_column_accuracy():
    result = scores(
        evaluate_sql(
            SQLEvaluationInput(
                actual_sql="select amount from fact_order where region = '华南'",
                expected_sql="select fact_order.amount from fact_order",
                execution_success=True,
            )
        )
    )

    assert result["sql_execution_success"] == 1.0
    assert result["schema_accuracy"] == 1.0
    assert result["table_selection_accuracy"] == 1.0
    assert result["column_accuracy"] == 1.0


def test_sql_metrics_do_not_use_simple_string_equality():
    result = scores(
        evaluate_sql(
            SQLEvaluationInput(
                actual_sql="SELECT amount FROM fact_order",
                expected_sql="select fact_order.amount from fact_order",
                execution_success=True,
            )
        )
    )

    assert result["table_selection_accuracy"] == 1.0
    assert result["column_accuracy"] == 1.0


def test_sql_metrics_invalid_actual_sql_scores_schema_zero():
    result = scores(
        evaluate_sql(
            SQLEvaluationInput(
                actual_sql="not sql",
                expected_sql="select amount from fact_order",
                execution_success=False,
            )
        )
    )

    assert result["schema_accuracy"] == 0.0
    assert result["sql_execution_success"] == 0.0
