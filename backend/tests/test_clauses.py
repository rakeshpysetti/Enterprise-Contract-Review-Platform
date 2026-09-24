from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine

from app.ai.chains.clause_chain import ClauseDetectionChain
from app.db.database import Base, get_session_factory
from app.db.models import Contract, ContractChunk
from app.db.repositories import ClauseRepository
from app.schemas.clause import ClauseDetection, ClauseType, DetectedClause
from app.services.clause_service import (
    ContractNotFoundError,
    InvalidClauseSourceError,
    detect_and_store_clauses,
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
def clause_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with get_session_factory(engine)() as session:
        yield session
    engine.dispose()


def make_contract(session):
    contract = Contract(title="Services", filename="services.pdf")
    contract.chunks = [
        ContractChunk(
            chunk_index=index,
            page_number=index + 1,
            content=text,
        )
        for index, text in enumerate(
            [
                "Either party may terminate this Agreement on thirty days notice.",
                "The term automatically renews for successive one-year periods.",
                "Customer shall pay all invoices within thirty days.",
                "Each party shall keep Confidential Information confidential.",
                "Supplier shall indemnify and hold Customer harmless from claims.",
                "Neither party's aggregate liability shall exceed fees paid.",
                "Provider guarantees 99.9% monthly service availability.",
                "Processor shall protect personal data under applicable privacy law.",
                "Disputes shall be resolved by binding arbitration in New York.",
            ]
        )
    ]
    session.add(contract)
    session.commit()
    return contract


def all_clause_results(contract) -> ClauseDetection:
    return ClauseDetection(
        clauses=[
            DetectedClause(
                clause_type=clause_type,
                source_text=contract.chunks[index].content,
                page_number=index + 1,
                confidence=0.95,
            )
            for index, clause_type in enumerate(ClauseType)
        ]
    )


def test_chain_uses_packaged_prompt_and_structured_output(clause_session):
    contract = make_contract(clause_session)
    expected = all_clause_results(contract)
    llm = MockStructuredLLM(expected)

    result = ClauseDetectionChain(llm).run(contract.chunks)

    assert result == expected
    prompt, schema, system = llm.calls[0]
    assert schema is ClauseDetection
    assert system is None
    assert "limitation_of_liability" in prompt
    assert "dispute_resolution" in prompt
    assert "[PAGE 9]" in prompt
    assert "{{CONTRACT_TEXT}}" not in prompt


def test_detects_all_supported_clause_types_with_evidence(clause_session):
    contract = make_contract(clause_session)

    result = detect_and_store_clauses(
        clause_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(all_clause_results(contract)),
    )

    assert [clause.clause_type for clause in result] == [item.value for item in ClauseType]
    assert all(clause.source_text for clause in result)
    assert [clause.page_number for clause in result] == list(range(1, 10))
    assert all(clause.confidence == pytest.approx(0.95) for clause in result)
    assert len(ClauseRepository(clause_session).list_for_contract(contract.id)) == 9


def test_source_validation_supports_multiple_chunks_on_one_page(clause_session):
    contract = Contract(title="Split", filename="split.pdf")
    contract.chunks = [
        ContractChunk(chunk_index=0, page_number=1, content="Either party may"),
        ContractChunk(
            chunk_index=1,
            page_number=1,
            content="terminate this Agreement on notice.",
        ),
    ]
    clause_session.add(contract)
    clause_session.commit()
    result = ClauseDetection(
        clauses=[
            DetectedClause(
                clause_type=ClauseType.termination,
                source_text="Either party may terminate this Agreement on notice.",
                page_number=1,
                confidence=0.9,
            )
        ]
    )

    detected = detect_and_store_clauses(
        clause_session,
        contract_id=contract.id,
        llm=MockStructuredLLM(result),
    )

    assert detected[0].source_text == result.clauses[0].source_text


@pytest.mark.parametrize(
    ("page_number", "source_text", "message"),
    [
        (99, "Either party may terminate", "unknown page"),
        (1, "This quote is not in the contract", "not found"),
    ],
)
def test_rejects_invalid_source_evidence(
    clause_session, page_number, source_text, message
):
    contract = make_contract(clause_session)
    result = ClauseDetection(
        clauses=[
            DetectedClause(
                clause_type=ClauseType.termination,
                source_text=source_text,
                page_number=page_number,
                confidence=0.9,
            )
        ]
    )

    with pytest.raises(InvalidClauseSourceError, match=message):
        detect_and_store_clauses(
            clause_session,
            contract_id=contract.id,
            llm=MockStructuredLLM(result),
        )


def test_missing_and_empty_contracts_are_rejected(clause_session):
    empty_result = ClauseDetection()
    with pytest.raises(ContractNotFoundError):
        detect_and_store_clauses(
            clause_session,
            contract_id=uuid4(),
            llm=MockStructuredLLM(empty_result),
        )
    empty = Contract(title="Empty", filename="empty.pdf")
    clause_session.add(empty)
    clause_session.commit()
    with pytest.raises(ValueError, match="does not contain text chunks"):
        detect_and_store_clauses(
            clause_session,
            contract_id=empty.id,
            llm=MockStructuredLLM(empty_result),
        )


def test_clause_schema_rejects_unsupported_type_and_invalid_evidence():
    with pytest.raises(ValidationError):
        DetectedClause.model_validate(
            {
                "clause_type": "warranty",
                "source_text": "",
                "page_number": 0,
                "confidence": 1.1,
                "unexpected": True,
            }
        )
