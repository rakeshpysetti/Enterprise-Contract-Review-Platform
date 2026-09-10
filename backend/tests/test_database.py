from datetime import date

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db.database import Base, get_session_factory
from app.db.models import (
    Contract,
    ContractChunk,
    ContractStatus,
    Obligation,
    Risk,
    RiskLevel,
)
from app.db.repositories import (
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
        Obligation(title="Pay invoices", description="Payment is due in 30 days")
    )
    contract.risks.append(
        Risk(
            title="Unlimited liability",
            description="Liability is not capped",
            level=RiskLevel.high,
            score=0.9,
        )
    )
    repository = ContractRepository(session)
    repository.add(contract)
    session.commit()

    stored = repository.get_with_details(contract.id)
    assert stored is not None
    assert stored.status is ContractStatus.uploaded
    assert stored.chunks[0].contract is stored
    assert stored.obligations[0].contract is stored
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
            Obligation(contract_id=first.id, title="Notify", description="Notify party"),
            Risk(
                contract_id=first.id,
                title="Renewal",
                description="Automatic renewal",
                level=RiskLevel.medium,
            ),
            ContractChunk(contract_id=second.id, chunk_index=0, content="unrelated"),
        ]
    )
    session.commit()

    assert [item.chunk_index for item in ContractChunkRepository(session).list_for_contract(first.id)] == [0, 1]
    assert len(ObligationRepository(session).list_for_contract(first.id)) == 1
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


def test_risk_schema_rejects_score_outside_probability_range():
    with pytest.raises(ValueError):
        RiskCreate(
            contract_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            title="Risk",
            description="Description",
            level=RiskLevel.low,
            score=1.1,
        )


def test_models_create_expected_tables(session: Session):
    tables = set(Base.metadata.tables)
    assert tables == {"contracts", "contract_chunks", "obligations", "risks"}
    assert session.scalar(select(Contract)) is None
