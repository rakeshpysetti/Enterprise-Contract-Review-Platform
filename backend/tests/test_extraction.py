from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from app.ai.chains.extraction_chain import ContractExtractionChain
from app.db.database import Base, get_session_factory
from app.db.models import Contract, ContractChunk
from app.schemas.contract import ContractMetadata, ContractParty, ContractRead
from app.services.analysis_service import (
    ContractNotFoundError,
    extract_and_store_contract_metadata,
)


class MockStructuredLLM:
    def __init__(self, result: ContractMetadata) -> None:
        self.result = result
        self.calls = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        raise AssertionError("Plain text generation should not be used")

    def generate_structured(self, prompt, schema, *, system=None):
        self.calls.append((prompt, schema, system))
        return self.result


@pytest.fixture
def extraction_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with get_session_factory(engine)() as session:
        yield session
    engine.dispose()


def extracted_metadata() -> ContractMetadata:
    return ContractMetadata(
        title="Master Services Agreement",
        contract_type="Master Services Agreement",
        parties=[
            ContractParty(name="Acme Corporation", role="Customer"),
            ContractParty(name="Example LLC", role="Provider"),
        ],
        effective_date=date(2026, 1, 1),
        expiration_date=date(2027, 1, 1),
        renewal_date=date(2027, 1, 1),
        governing_law="State of New York",
        payment_terms="USD invoices are due within 30 days of receipt.",
    )


def test_chain_uses_packaged_prompt_page_order_and_structured_schema():
    llm = MockStructuredLLM(extracted_metadata())
    chunks = [
        ContractChunk(chunk_index=1, page_number=3, content="Payment is due in 30 days."),
        ContractChunk(chunk_index=0, page_number=1, content="MASTER SERVICES AGREEMENT"),
    ]
    result = ContractExtractionChain(llm).run(chunks)

    assert result.title == "Master Services Agreement"
    prompt, schema, system = llm.calls[0]
    assert schema is ContractMetadata
    assert system is None
    assert prompt.index("[PAGE 1]") < prompt.index("[PAGE 3]")
    assert "Do not infer" in prompt
    assert "{{CONTRACT_TEXT}}" not in prompt


def test_extraction_persists_all_contract_metadata(extraction_session):
    contract = Contract(title="uploaded-file", filename="agreement.pdf")
    contract.chunks = [
        ContractChunk(chunk_index=0, page_number=1, content="Contract text")
    ]
    extraction_session.add(contract)
    extraction_session.commit()
    llm = MockStructuredLLM(extracted_metadata())

    result = extract_and_store_contract_metadata(
        extraction_session, contract_id=contract.id, llm=llm
    )
    extraction_session.commit()
    extraction_session.refresh(contract)

    assert result.contract_type == "Master Services Agreement"
    assert contract.title == "Master Services Agreement"
    assert contract.contract_type == "Master Services Agreement"
    assert contract.parties == [
        {"name": "Acme Corporation", "role": "Customer"},
        {"name": "Example LLC", "role": "Provider"},
    ]
    assert contract.effective_date == date(2026, 1, 1)
    assert contract.expiration_date == date(2027, 1, 1)
    assert contract.renewal_date == date(2027, 1, 1)
    assert contract.governing_law == "State of New York"
    assert contract.payment_terms == "USD invoices are due within 30 days of receipt."
    assert ContractRead.model_validate(contract).parties[0].name == "Acme Corporation"


def test_null_extracted_title_preserves_uploaded_title(extraction_session):
    contract = Contract(title="Uploaded title", filename="agreement.pdf")
    contract.chunks = [ContractChunk(chunk_index=0, content="No formal title")]
    extraction_session.add(contract)
    extraction_session.commit()
    metadata = ContractMetadata(title=None, contract_type=None, parties=[])

    extract_and_store_contract_metadata(
        extraction_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(metadata),
    )
    assert contract.title == "Uploaded title"
    assert contract.parties == []


def test_extraction_reports_missing_contract_and_empty_chunks(extraction_session):
    with pytest.raises(ContractNotFoundError):
        extract_and_store_contract_metadata(
            extraction_session,
            contract_id=uuid4(),
            llm=MockStructuredLLM(extracted_metadata()),
        )

    empty = Contract(title="Empty", filename="empty.pdf")
    extraction_session.add(empty)
    extraction_session.commit()
    with pytest.raises(ValueError, match="does not contain text chunks"):
        extract_and_store_contract_metadata(
            extraction_session,
            contract_id=empty.id,
            llm=MockStructuredLLM(extracted_metadata()),
        )


def test_structured_schema_rejects_invalid_dates_and_extra_fields():
    with pytest.raises(ValidationError):
        ContractMetadata.model_validate(
            {
                "title": "Agreement",
                "contract_type": "NDA",
                "parties": [],
                "effective_date": "January 1st",
                "unknown_field": "not allowed",
            }
        )
