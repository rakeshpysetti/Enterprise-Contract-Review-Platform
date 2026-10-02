import pytest
from app.services.chunking_service import clean_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Payment\t is   due  ", "Payment is due"),
        ("first\r\nsecond\rthird", "first\nsecond\nthird"),
        ("first\n\n\n\nsecond", "first\n\nsecond"),
        ("non\u00a0breaking space", "non breaking space"),
        (" \t\r\n ", ""),
    ],
)
def test_clean_text_normalizes_contract_text(raw: str, expected: str) -> None:
    assert clean_text(raw) == expected
