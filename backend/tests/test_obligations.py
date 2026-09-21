from datetime import date
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine

from app.ai.chains.obligation_chain import ObligationExtractionChain
from app.db.database import Base, get_session_factory
from app.db.models import Contract, ContractChunk, Obligation, ObligationPriority
from app.db.repositories import ObligationRepository
from app.schemas.obligation import ExtractedObligation, ObligationExtraction, ObligationRead
from app.services.obligation_service import (
    ContractNotFoundError,
    InvalidObligationSourceError,
    extract_and_store_obligations,
)


class MockStructuredLLM:
    def __init__(self, result: BaseModel) -> None:
        self.result = result
        self.calls = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        raise AssertionError("Plain text generation should not be used")

    def generate_structured(self, prompt, schema, *, system=None):
        self.calls.append((prompt, schema, system))
        return self.result


@pytest.fixture
def obligation_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with get_session_factory(engine)() as session:
        yield session
    engine.dispose()


def extraction_result() -> ObligationExtraction:
    return ObligationExtraction(
        obligations=[
            ExtractedObligation(
                title="Pay monthly service fees",
                description="Customer must pay each invoice within 30 days.",
                responsible_party="Customer",
                counterparty="Provider",
                due_date=date(2026, 2, 15),
                recurring_frequency="monthly; within 30 days after each invoice",
                priority=ObligationPriority.high,
                source_text="Customer shall pay each monthly invoice within 30 days.",
                page_number=2,
                confidence=0.97,
            )
        ]
    )


def make_contract(session):
    contract = Contract(title="Services", filename="services.pdf")
    contract.chunks = [
        ContractChunk(chunk_index=0, page_number=1, content="Agreement introduction."),
        ContractChunk(
            chunk_index=1,
            page_number=2,
            content="Customer shall pay each monthly invoice within 30 days.",
        ),
    ]
    session.add(contract)
    session.commit()
    return contract


def test_chain_uses_packaged_prompt_and_structured_output(obligation_session):
    contract = make_contract(obligation_session)
    llm = MockStructuredLLM(extraction_result())
    result = ObligationExtractionChain(llm).run(contract.chunks)

    assert len(result.obligations) == 1
    prompt, schema, system = llm.calls[0]
    assert schema is ObligationExtraction
    assert system is None
    assert "responsible party" in prompt
    assert "[PAGE 2]" in prompt
    assert "{{CONTRACT_TEXT}}" not in prompt


def test_obligations_are_validated_and_persisted(obligation_session):
    contract = make_contract(obligation_session)
    created = extract_and_store_obligations(
        obligation_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(extraction_result()),
    )
    obligation_session.commit()

    stored = ObligationRepository(obligation_session).list_for_contract(contract.id)
    assert [item.id for item in stored] == [created[0].id]
    assert stored[0].responsible_party == "Customer"
    assert stored[0].counterparty == "Provider"
    assert stored[0].due_date == date(2026, 2, 15)
    assert stored[0].recurring_frequency == "monthly; within 30 days after each invoice"
    assert stored[0].priority is ObligationPriority.high
    assert stored[0].page_number == 2
    assert stored[0].confidence == pytest.approx(0.97)
    assert ObligationRead.model_validate(stored[0]).source_text.startswith("Customer")


def test_source_validation_supports_multiple_chunks_on_one_page(obligation_session):
    contract = Contract(title="Split page", filename="split.pdf")
    contract.chunks = [
        ContractChunk(chunk_index=0, page_number=1, content="Customer shall pay each"),
        ContractChunk(
            chunk_index=1,
            page_number=1,
            content="monthly invoice within 30 days.",
        ),
    ]
    obligation_session.add(contract)
    obligation_session.commit()
    result = extraction_result()
    result.obligations[0].page_number = 1

    created = extract_and_store_obligations(
        obligation_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(result),
    )

    assert created[0].page_number == 1


def test_reextraction_replaces_existing_obligations(obligation_session):
    contract = make_contract(obligation_session)
    old = Obligation(
        contract_id=contract.id,
        title="Old",
        description="Old extraction",
        priority=ObligationPriority.low,
        source_text="Agreement introduction.",
        page_number=1,
        confidence=0.4,
    )
    obligation_session.add(old)
    obligation_session.commit()

    created = extract_and_store_obligations(
        obligation_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(extraction_result()),
    )
    obligation_session.commit()
    stored = ObligationRepository(obligation_session).list_for_contract(contract.id)
    assert len(stored) == 1
    assert stored[0].id == created[0].id
    assert stored[0].id != old.id


@pytest.mark.parametrize(
    ("page_number", "source_text", "message"),
    [
        (99, "Customer shall pay", "unknown page"),
        (2, "A source quote that is not present", "not found"),
    ],
)
def test_invalid_sources_do_not_replace_existing_data(
    obligation_session, page_number, source_text, message
):
    contract = make_contract(obligation_session)
    existing = Obligation(
        contract_id=contract.id,
        title="Existing",
        description="Existing obligation",
        priority=ObligationPriority.medium,
        source_text="Agreement introduction.",
        page_number=1,
        confidence=0.8,
    )
    obligation_session.add(existing)
    obligation_session.commit()
    invalid = extraction_result()
    invalid.obligations[0].page_number = page_number
    invalid.obligations[0].source_text = source_text

    with pytest.raises(InvalidObligationSourceError, match=message):
        extract_and_store_obligations(
            obligation_session,
            contract_id=contract.id,
            llm=MockStructuredLLM(invalid),
        )
    obligation_session.expire_all()
    assert ObligationRepository(obligation_session).list_for_contract(contract.id)[0].id == existing.id


def test_missing_and_empty_contracts_are_rejected(obligation_session):
    with pytest.raises(ContractNotFoundError):
        extract_and_store_obligations(
            obligation_session,
            contract_id=uuid4(),
            llm=MockStructuredLLM(extraction_result()),
        )
    empty = Contract(title="Empty", filename="empty.pdf")
    obligation_session.add(empty)
    obligation_session.commit()
    with pytest.raises(ValueError, match="does not contain text chunks"):
        extract_and_store_obligations(
            obligation_session,
            contract_id=empty.id,
            llm=MockStructuredLLM(extraction_result()),
        )


def test_obligation_schema_rejects_invalid_priority_confidence_and_extra_fields():
    payload = {
        "title": "Pay",
        "description": "Pay invoice",
        "responsible_party": "Customer",
        "counterparty": "Provider",
        "due_date": "not-a-date",
        "recurring_frequency": "monthly",
        "priority": "urgent",
        "source_text": "Customer shall pay",
        "page_number": 0,
        "confidence": 1.5,
        "unexpected": True,
    }
    with pytest.raises(ValidationError):
        ExtractedObligation.model_validate(payload)
