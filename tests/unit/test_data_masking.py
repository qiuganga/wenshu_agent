from app.security.data_masking import mask_row, mask_rows, mask_value


def test_mask_sensitive_values():
    assert mask_value("mobile", "13812345678") == "138****5678"
    assert mask_value("id_card", "110101199001011234") == "110********1234"
    assert mask_value("email", "alice@example.com") == "al***@example.com"
    assert mask_value("password", "secret") == "***"
    assert mask_value("api_key", "sk-xxx") == "***"
    assert mask_value("bank_card", "6222020202021234") == "****1234"


def test_unknown_and_none_values_unchanged():
    assert mask_value("amount", 100) == 100
    assert mask_value("mobile", None) is None


def test_mask_row_and_rows():
    row = mask_row({"mobile": "13812345678", "amount": 10})
    assert row == {"mobile": "138****5678", "amount": 10}
    assert mask_rows([{"email": "a@example.com"}]) == [{"email": "a***@example.com"}]
