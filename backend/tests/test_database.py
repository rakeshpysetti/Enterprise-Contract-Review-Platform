from datetime import date

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db.database import Base, get_session_factory
from app.db.models import (
    Contract,
    Clause,
    ContractChunk,
    ContractStatus,
    Obligation,
    ObligationPriority,
    Risk,
    RiskLevel,
)
from app.db.repositories import (
    ClauseRepository,
    ContractChunkRepository,
    ContractRepository,
    ObligationRepository,
    RiskRepository,
)
from app.schemas.contract import ContractChunkRead, ContractRead
from app.schemas.obligation import ObligationRead
from app.schemas.risk import RiskCreate, RiskRead


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with get_session_factory(engine)() as database_session:
        yield database_session
    engine.dispose()


def test_contract_relationships_and_schema_serialization(session: Session):
    contract = Contract(
        title="Master Services Agreement",
        filename="msa.pdf",
        effective_date=date(2026, 1, 1),
    )
    contract.chunks.append(ContractChunk(chunk_index=0, content="Payment terms"))
    contract.obligations.append(
        Obligation(
            title="Pay invoices",
            description="Payment is due in 30 days",
            priority=ObligationPriority.high,
            source_text="Payment is due in 30 days",
            page_number=1,
            confidence=0.95,
        )
    )
    contract.clauses.append(
        Clause(
            clause_type="payment",
            source_text="Payment is due in 30 days",
            page_number=1,
            confidence=0.94,
        )
    )
    contract.risks.append(
        Risk(
            category="Liability",
            description="Liability is not capped",
            level=RiskLevel.high,
            why_it_matters="This may create material exposure.",
            recommendation="Consider reviewing a liability cap.",
            source_text="Liability is not capped",
            page_number=1,
            confidence=0.9,
        )
    )
    repository = ContractRepository(session)
    repository.add(contract)
    session.commit()

    stored = repository.get_with_details(contract.id)
    assert stored is not None
    assert stored.status is ContractStatus.pending
    assert stored.chunks[0].contract is stored
    assert stored.obligations[0].contract is stored
    assert stored.clauses[0].contract is stored
    assert stored.risks[0].contract is stored
    assert ContractRead.model_validate(stored).filename == "msa.pdf"
    assert ContractChunkRead.model_validate(stored.chunks[0]).chunk_index == 0
    assert ObligationRead.model_validate(stored.obligations[0]).title == "Pay invoices"
    assert RiskRead.model_validate(stored.risks[0]).level is RiskLevel.high


def test_repositories_filter_related_records(session: Session):
    first = Contract(title="First", filename="first.pdf")
    second = Contract(title="Second", filename="second.pdf")
    session.add_all([first, second])
    session.flush()
    session.add_all(
        [
            ContractChunk(contract_id=first.id, chunk_index=1, content="second"),
            ContractChunk(contract_id=first.id, chunk_index=0, content="first"),
            Obligation(
                contract_id=first.id,
                title="Notify",
                description="Notify party",
                priority=ObligationPriority.medium,
                source_text="Notify party",
                page_number=1,
                confidence=0.9,
            ),
            Risk(
                contract_id=first.id,
                category="Renewal",
                description="Automatic renewal",
                level=RiskLevel.medium,
                why_it_matters="This may extend the term unexpectedly.",
                recommendation="Consider reviewing the notice period.",
                source_text="Automatic renewal",
                page_number=1,
                confidence=0.8,
            ),
            Clause(
                contract_id=first.id,
                clause_type="renewal",
                source_text="Automatic renewal",
                page_number=1,
                confidence=0.85,
            ),
            ContractChunk(contract_id=second.id, chunk_index=0, content="unrelated"),
        ]
    )
    session.commit()

    assert [item.chunk_index for item in ContractChunkRepository(session).list_for_contract(first.id)] == [0, 1]
    assert len(ObligationRepository(session).list_for_contract(first.id)) == 1
    assert len(ClauseRepository(session).list_for_contract(first.id)) == 1
    assert len(RiskRepository(session).list_for_contract(first.id)) == 1
    assert len(ContractRepository(session).list(limit=1)) == 1


def test_delete_contract_cascades_to_children(session: Session):
    contract = Contract(title="Delete me", filename="delete.pdf")
    contract.chunks.append(ContractChunk(chunk_index=0, content="content"))
    ContractRepository(session).add(contract)
    session.commit()
    chunk_id = contract.chunks[0].id

    ContractRepository(session).delete(contract)
    session.commit()
    assert session.get(ContractChunk, chunk_id) is None


def test_risk_schema_rejects_confidence_outside_probability_range():
    with pytest.raises(ValueError):
        RiskCreate(
            contract_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            category="Risk",
            description="Description",
            level=RiskLevel.low,
            why_it_matters="This may matter.",
            recommendation="Consider review.",
            source_text="Source",
            page_number=1,
            confidence=1.1,
        )


def test_models_create_expected_tables(session: Session):
    tables = set(Base.metadata.tables)
    assert tables == {"contracts", "contract_chunks", "obligations", "clauses", "risks"}
    assert session.scalar(select(Contract)) is None
