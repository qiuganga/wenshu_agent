import pytest
from pydantic import ValidationError

from app.config.meta_config import load_meta_config_data


def _valid_meta_config():
    return {
        "tables": [
            {
                "name": "fact_order",
                "role": "fact",
                "description": "orders",
                "columns": [
                    {
                        "name": "order_amount",
                        "role": "measure",
                        "description": "amount",
                        "alias": ["amount"],
                        "sync": False,
                    }
                ],
            }
        ],
        "metrics": [
            {
                "name": "GMV",
                "description": "total amount",
                "relevant_columns": ["fact_order.order_amount"],
                "alias": ["sales"],
            }
        ],
    }


def test_meta_config_parse_success():
    config = load_meta_config_data(_valid_meta_config())

    assert config.tables[0].name == "fact_order"
    assert config.metrics[0].relevant_columns == ["fact_order.order_amount"]


def test_meta_config_duplicate_table_fails():
    data = _valid_meta_config()
    data["tables"].append(data["tables"][0])

    with pytest.raises(ValidationError, match="duplicate table name: fact_order"):
        load_meta_config_data(data)


def test_meta_config_duplicate_column_fails():
    data = _valid_meta_config()
    data["tables"][0]["columns"].append(data["tables"][0]["columns"][0])

    with pytest.raises(ValidationError, match="duplicate column id: fact_order.order_amount"):
        load_meta_config_data(data)


def test_meta_config_invalid_relevant_column_fails():
    data = _valid_meta_config()
    data["metrics"][0]["relevant_columns"] = ["fact_order.missing_column"]

    with pytest.raises(ValidationError, match="references undefined column: fact_order.missing_column"):
        load_meta_config_data(data)
