import pytest
from app.services.chunking_service import clean_text, split_page_text


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


def test_long_page_is_split_without_losing_source_order() -> None:
    sentence = "Customer shall pay each undisputed invoice within 30 days."
    text = " ".join([sentence] * 160)
    chunks = split_page_text(text)
    assert len(chunks) > 1
    assert all(chunk and len(chunk) < len(text) for chunk in chunks)
    assert all("Customer shall pay" in chunk for chunk in chunks)
    assert chunks[0].startswith("Customer")
    assert chunks[-1].endswith("days.")
    assert split_page_text("Short page") == ["Short page"]


def test_moderate_page_is_split_before_embedding_truncation() -> None:
    text = " ".join(
        ["The supplier shall provide a monthly compliance report to the customer."] * 28
    )
    assert len(text) < 4000
    chunks = split_page_text(text)
    assert len(chunks) > 1
    assert all("monthly compliance report" in chunk for chunk in chunks)
