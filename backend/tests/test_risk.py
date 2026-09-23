from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine

from app.ai.chains.risk_chain import RiskExtractionChain
from app.db.database import Base, get_session_factory
from app.db.models import Contract, ContractChunk, Risk, RiskLevel
from app.db.repositories import RiskRepository
from app.schemas.risk import ExtractedRisk, RiskExtraction, RiskRead
from app.services.risk_service import (
    ContractNotFoundError,
    InvalidRiskSourceError,
    extract_and_store_risks,
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
def risk_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with get_session_factory(engine)() as session:
        yield session
    engine.dispose()


def extraction_result(level: RiskLevel = RiskLevel.high) -> RiskExtraction:
    return RiskExtraction(
        risks=[
            ExtractedRisk(
                category="Limitation of liability",
                description="The agreement does not state an aggregate liability cap.",
                level=level,
                why_it_matters="This may create exposure beyond anticipated fees.",
                recommendation="Consider reviewing whether an appropriate cap should be negotiated.",
                source_text="Supplier's liability shall be unlimited.",
                page_number=2,
                confidence=0.96,
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
            content="Supplier's liability shall be unlimited.",
        ),
    ]
    session.add(contract)
    session.commit()
    return contract


def test_chain_uses_packaged_prompt_and_cautious_review_language(risk_session):
    contract = make_contract(risk_session)
    llm = MockStructuredLLM(extraction_result())

    result = RiskExtractionChain(llm).run(contract.chunks)

    assert len(result.risks) == 1
    prompt, schema, system = llm.calls[0]
    assert schema is RiskExtraction
    assert system is None
    assert "low, medium, high, or critical" in prompt
    assert 'cautious language such as "may", "could", or' in prompt
    assert "rather than issuing legal advice" in prompt
    assert "[PAGE 2]" in prompt
    assert "{{CONTRACT_TEXT}}" not in prompt


@pytest.mark.parametrize("level", list(RiskLevel))
def test_all_severity_levels_are_supported(level):
    assert extraction_result(level).risks[0].level is level


def test_risks_are_validated_and_persisted(risk_session):
    contract = make_contract(risk_session)

    created = extract_and_store_risks(
        risk_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(extraction_result()),
    )
    risk_session.commit()

    stored = RiskRepository(risk_session).list_for_contract(contract.id)
    assert [item.id for item in stored] == [created[0].id]
    assert stored[0].category == "Limitation of liability"
    assert stored[0].level is RiskLevel.high
    assert stored[0].why_it_matters.startswith("This may")
    assert stored[0].recommendation.startswith("Consider reviewing")
    assert stored[0].source_text == "Supplier's liability shall be unlimited."
    assert stored[0].page_number == 2
    assert stored[0].confidence == pytest.approx(0.96)
    assert RiskRead.model_validate(stored[0]).description.startswith("The agreement")


def test_source_validation_supports_multiple_chunks_on_one_page(risk_session):
    contract = Contract(title="Split page", filename="split.pdf")
    contract.chunks = [
        ContractChunk(chunk_index=0, page_number=1, content="Supplier's liability"),
        ContractChunk(chunk_index=1, page_number=1, content="shall be unlimited."),
    ]
    risk_session.add(contract)
    risk_session.commit()
    result = extraction_result()
    result.risks[0].page_number = 1

    created = extract_and_store_risks(
        risk_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(result),
    )

    assert created[0].page_number == 1


def test_reextraction_replaces_existing_risks(risk_session):
    contract = make_contract(risk_session)
    existing = Risk(
        contract_id=contract.id,
        category="Old",
        description="Old result",
        level=RiskLevel.low,
        why_it_matters="This may matter.",
        recommendation="Consider review.",
        source_text="Agreement introduction.",
        page_number=1,
        confidence=0.4,
    )
    risk_session.add(existing)
    risk_session.commit()

    created = extract_and_store_risks(
        risk_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(extraction_result()),
    )
    risk_session.commit()

    stored = RiskRepository(risk_session).list_for_contract(contract.id)
    assert len(stored) == 1
    assert stored[0].id == created[0].id
    assert stored[0].id != existing.id


@pytest.mark.parametrize(
    ("page_number", "source_text", "message"),
    [
        (99, "Supplier's liability", "unknown page"),
        (2, "A quote that is not present", "not found"),
    ],
)
def test_invalid_sources_do_not_replace_existing_risks(
    risk_session, page_number, source_text, message
):
    contract = make_contract(risk_session)
    existing = Risk(
        contract_id=contract.id,
        category="Existing",
        description="Existing result",
        level=RiskLevel.medium,
        why_it_matters="This could matter.",
        recommendation="Confirm the commercial position.",
        source_text="Agreement introduction.",
        page_number=1,
        confidence=0.8,
    )
    risk_session.add(existing)
    risk_session.commit()
    invalid = extraction_result()
    invalid.risks[0].page_number = page_number
    invalid.risks[0].source_text = source_text

    with pytest.raises(InvalidRiskSourceError, match=message):
        extract_and_store_risks(
            risk_session,
            contract_id=contract.id,
            llm=MockStructuredLLM(invalid),
        )
    risk_session.expire_all()
    assert RiskRepository(risk_session).list_for_contract(contract.id)[0].id == existing.id


def test_missing_and_empty_contracts_are_rejected(risk_session):
    with pytest.raises(ContractNotFoundError):
        extract_and_store_risks(
            risk_session,
            contract_id=uuid4(),
            llm=MockStructuredLLM(extraction_result()),
        )
    empty = Contract(title="Empty", filename="empty.pdf")
    risk_session.add(empty)
    risk_session.commit()
    with pytest.raises(ValueError, match="does not contain text chunks"):
        extract_and_store_risks(
            risk_session,
            contract_id=empty.id,
            llm=MockStructuredLLM(RiskExtraction()),
        )


def test_risk_schema_rejects_invalid_level_confidence_page_and_extra_fields():
    with pytest.raises(ValidationError):
        ExtractedRisk.model_validate(
            {
                "category": "Liability",
                "description": "Description",
                "level": "severe",
                "why_it_matters": "Could matter",
                "recommendation": "Review",
                "source_text": "Source",
                "page_number": 0,
                "confidence": 1.2,
                "unexpected": True,
            }
        )
