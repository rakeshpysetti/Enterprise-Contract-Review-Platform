from datetime import date
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.db.database import Base, get_db, get_session_factory
from app.db.models import (
    Clause,
    Contract,
    ContractStatus,
    Obligation,
    ObligationPriority,
    Risk,
    RiskLevel,
)
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


def make_risk(level: RiskLevel, page_number: int) -> Risk:
    return Risk(
        category=f"{level.value.title()} risk",
        description=f"A {level.value} issue",
        level=level,
        why_it_matters="This may affect the agreement.",
        recommendation="Consider reviewing this issue.",
        source_text=f"Source for {level.value} risk",
        page_number=page_number,
        confidence=0.9,
    )


@pytest.fixture
def summary_api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        analyzed = Contract(
            title="Master Services Agreement",
            filename="msa.pdf",
            contract_type="MSA",
            status=ContractStatus.completed,
            effective_date=date(2026, 1, 1),
            expiration_date=date(2027, 1, 1),
            renewal_date=date(2026, 11, 1),
        )
        analyzed.obligations = [
            Obligation(
                title="Pay invoices",
                description="Pay invoices within 30 days",
                priority=ObligationPriority.high,
                source_text="Pay invoices within 30 days",
                page_number=2,
                confidence=0.95,
            ),
            Obligation(
                title="Send notice",
                description="Send notice before renewal",
                priority=ObligationPriority.medium,
                source_text="Send notice before renewal",
                page_number=4,
                confidence=0.9,
            ),
        ]
        analyzed.risks = [
            make_risk(RiskLevel.low, 1),
            make_risk(RiskLevel.medium, 2),
            make_risk(RiskLevel.high, 3),
            make_risk(RiskLevel.high, 4),
            make_risk(RiskLevel.critical, 5),
        ]
        analyzed.clauses = [
            Clause(
                clause_type="termination",
                source_text="Either party may terminate on 60 days notice.",
                page_number=6,
                confidence=0.94,
            ),
            Clause(
                clause_type="payment",
                source_text="Invoices are due within 30 days.",
                page_number=2,
                confidence=0.97,
            ),
        ]
        empty = Contract(title="Pending Contract", filename="pending.pdf")
        low_only = Contract(title="Low Risk", filename="low.pdf")
        low_only.risks = [make_risk(RiskLevel.low, 1)]
        session.add_all([analyzed, empty, low_only])
        session.commit()
        identifiers = analyzed.id, empty.id, low_only.id

    app = create_app(Settings(_env_file=None, app_env="test"))

    def override_database():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    with TestClient(app) as client:
        yield client, identifiers
    engine.dispose()


def test_summary_returns_counts_dates_clauses_and_overall_risk(summary_api):
    client, (contract_id, _, _) = summary_api

    response = client.get(f"/contracts/{contract_id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_id"] == str(contract_id)
    assert body["title"] == "Master Services Agreement"
    assert body["contract_type"] == "MSA"
    assert body["status"] == "completed"
    assert body["risk_counts"] == {
        "low": 1,
        "medium": 1,
        "high": 2,
        "critical": 1,
        "total": 5,
    }
    assert body["obligation_count"] == 2
    assert body["important_dates"] == {
        "effective_date": "2026-01-01",
        "expiration_date": "2027-01-01",
        "renewal_date": "2026-11-01",
    }
    assert body["overall_risk_level"] == "critical"
    assert body["key_clauses"] == [
        {
            "clause_type": "payment",
            "source_excerpt": "Invoices are due within 30 days.",
            "page_number": 2,
            "confidence": 0.97,
        },
        {
            "clause_type": "termination",
            "source_excerpt": "Either party may terminate on 60 days notice.",
            "page_number": 6,
            "confidence": 0.94,
        },
    ]


def test_summary_returns_zero_counts_and_nulls_without_analysis(summary_api):
    client, (_, contract_id, _) = summary_api

    response = client.get(f"/contracts/{contract_id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["risk_counts"] == {
        "low": 0,
        "medium": 0,
        "high": 0,
        "critical": 0,
        "total": 0,
    }
    assert body["obligation_count"] == 0
    assert body["important_dates"] == {
        "effective_date": None,
        "expiration_date": None,
        "renewal_date": None,
    }
    assert body["key_clauses"] == []
    assert body["overall_risk_level"] is None


def test_summary_uses_highest_present_risk_not_highest_enum(summary_api):
    client, (_, _, contract_id) = summary_api

    response = client.get(f"/contracts/{contract_id}/summary")

    assert response.status_code == 200
    assert response.json()["overall_risk_level"] == "low"
    assert response.json()["risk_counts"]["low"] == 1


def test_summary_reports_missing_contract(summary_api):
    client, _ = summary_api
    response = client.get(f"/contracts/{uuid4()}/summary")
    assert response.status_code == 404
    assert response.json()["detail"] == "Contract not found"
