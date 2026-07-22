from app.security.masking import DataMasker, FieldMaskingRule


def test_data_masker_masks_sensitive_fields():
    masker = DataMasker(
        [
            FieldMaskingRule("email", "SENSITIVE"),
            FieldMaskingRule("phone", "SENSITIVE"),
            FieldMaskingRule("id_card", "SECRET"),
        ]
    )

    row = masker.mask_row(
        {
            "email": "alice@example.com",
            "phone": "13812345678",
            "id_card": "110101199001011234",
            "amount": 10,
        }
    )

    assert row["email"] == "al***@example.com"
    assert row["phone"] == "138****5678"
    assert row["id_card"] == "110********1234"
    assert row["amount"] == 10


def test_public_fields_are_not_masked():
    masker = DataMasker([FieldMaskingRule("amount", "PUBLIC")])

    assert masker.mask_row({"amount": 100}) == {"amount": 100}
