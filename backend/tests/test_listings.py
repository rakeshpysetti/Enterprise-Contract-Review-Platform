from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.db.database import Base, get_db, get_session_factory
from app.db.models import (
    Clause,
    Contract,
    Obligation,
    ObligationPriority,
    Risk,
    RiskLevel,
)
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
def listing_api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        msa = Contract(
            title="Acme MSA",
            filename="acme.pdf",
            contract_type="Master Services Agreement",
            expiration_date=date(2027, 6, 30),
            renewal_date=date(2027, 5, 1),
            parties=[
                {"name": "Acme Corporation", "role": "Customer"},
                {"name": "Provider LLC", "role": "Provider"},
            ],
            created_at=now,
        )
        nda = Contract(
            title="Beta NDA",
            filename="beta.pdf",
            contract_type="NDA",
            expiration_date=date(2026, 12, 31),
            renewal_date=None,
            parties=[{"name": "Beta Holdings", "role": "Discloser"}],
            created_at=now - timedelta(days=1),
        )
        order_form = Contract(
            title="Gamma Order",
            filename="gamma.pdf",
            contract_type="Order Form",
            expiration_date=None,
            renewal_date=date(2028, 1, 15),
            parties=[{"name": "Gamma Industries", "role": "Buyer"}],
            created_at=now - timedelta(days=2),
        )
        msa.obligations = [
            Obligation(
                title="Low task",
                description="Low priority task",
                priority=ObligationPriority.low,
                source_text="Low priority task",
                page_number=1,
                confidence=0.8,
            ),
            Obligation(
                title="Critical task",
                description="Critical priority task",
                priority=ObligationPriority.critical,
                source_text="Critical priority task",
                page_number=3,
                confidence=0.98,
            ),
        ]
        msa.risks = [
            Risk(
                category="Renewal",
                description="Renewal risk",
                level=RiskLevel.medium,
                why_it_matters="This may extend the agreement.",
                recommendation="Consider reviewing notice dates.",
                source_text="Renews automatically",
                page_number=2,
                confidence=0.86,
            ),
            Risk(
                category="Liability",
                description="Unlimited liability",
                level=RiskLevel.critical,
                why_it_matters="This may create substantial exposure.",
                recommendation="Consider reviewing a liability cap.",
                source_text="Liability is unlimited",
                page_number=5,
                confidence=0.97,
            ),
        ]
        msa.clauses = [
            Clause(
                clause_type="payment",
                source_text="Invoices are due in 30 days",
                page_number=1,
                confidence=0.96,
            ),
            Clause(
                clause_type="termination",
                source_text="Either party may terminate",
                page_number=4,
                confidence=0.93,
            ),
        ]
        nda.obligations = [
            Obligation(
                title="Protect information",
                description="Keep information confidential",
                priority=ObligationPriority.high,
                source_text="Keep information confidential",
                page_number=2,
                confidence=0.95,
            )
        ]
        session.add_all([msa, nda, order_form])
        session.commit()
        identifiers = msa.id, nda.id, order_form.id

    app = create_app(Settings(_env_file=None, app_env="test"))

    def override_database():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    with TestClient(app) as client:
        yield client, identifiers
    engine.dispose()


def ids(response) -> list[str]:
    assert response.status_code == 200
    return [item["id"] for item in response.json()]


def test_contract_listing_supports_type_and_party_filters(listing_api):
    client, (msa_id, nda_id, _) = listing_api

    assert ids(client.get("/contracts", params={"contract_type": "nda"})) == [
        str(nda_id)
    ]
    assert ids(client.get("/contracts", params={"party": "ACME"})) == [str(msa_id)]
    assert ids(client.get("/contracts", params={"party": "hold"})) == [str(nda_id)]


def test_contract_listing_supports_expiration_and_renewal_ranges(listing_api):
    client, (msa_id, nda_id, order_id) = listing_api

    expiring_2026 = client.get(
        "/contracts",
        params={
            "expiration_date_from": "2026-01-01",
            "expiration_date_to": "2026-12-31",
        },
    )
    renewing_after_2027 = client.get(
        "/contracts", params={"renewal_date_from": "2027-06-01"}
    )
    combined = client.get(
        "/contracts",
        params={
            "contract_type": "Master Services Agreement",
            "expiration_date_to": "2027-12-31",
            "renewal_date_from": "2027-01-01",
            "party": "Provider",
        },
    )

    assert ids(expiring_2026) == [str(nda_id)]
    assert ids(renewing_after_2027) == [str(order_id)]
    assert ids(combined) == [str(msa_id)]


def test_contract_listing_paginates_after_party_filtering(listing_api):
    client, (msa_id, _, _) = listing_api

    first = client.get("/contracts", params={"party": "Provider", "limit": 1})
    skipped = client.get(
        "/contracts", params={"party": "Provider", "offset": 1, "limit": 1}
    )

    assert ids(first) == [str(msa_id)]
    assert skipped.json() == []


def test_obligation_listing_is_scoped_filtered_and_paginated(listing_api):
    client, (msa_id, nda_id, _) = listing_api

    all_items = client.get(f"/contracts/{msa_id}/obligations")
    critical = client.get(
        f"/contracts/{msa_id}/obligations", params={"priority": "critical"}
    )
    second_page = client.get(
        f"/contracts/{msa_id}/obligations", params={"offset": 1, "limit": 1}
    )

    assert [item["title"] for item in all_items.json()] == [
        "Low task",
        "Critical task",
    ]
    assert [item["title"] for item in critical.json()] == ["Critical task"]
    assert [item["title"] for item in second_page.json()] == ["Critical task"]
    assert all(item["contract_id"] == str(msa_id) for item in all_items.json())
    assert client.get(f"/contracts/{nda_id}/obligations").json()[0]["title"] == (
        "Protect information"
    )


def test_risk_listing_is_scoped_and_filters_by_severity(listing_api):
    client, (msa_id, nda_id, _) = listing_api

    all_items = client.get(f"/contracts/{msa_id}/risks")
    critical = client.get(f"/contracts/{msa_id}/risks", params={"severity": "critical"})

    assert [item["category"] for item in all_items.json()] == [
        "Renewal",
        "Liability",
    ]
    assert [item["category"] for item in critical.json()] == ["Liability"]
    assert client.get(f"/contracts/{nda_id}/risks").json() == []


def test_clause_listing_is_scoped_and_paginated(listing_api):
    client, (msa_id, nda_id, _) = listing_api

    all_items = client.get(f"/contracts/{msa_id}/clauses")
    second_page = client.get(
        f"/contracts/{msa_id}/clauses", params={"offset": 1, "limit": 1}
    )

    assert [item["clause_type"] for item in all_items.json()] == [
        "payment",
        "termination",
    ]
    assert [item["clause_type"] for item in second_page.json()] == ["termination"]
    assert client.get(f"/contracts/{nda_id}/clauses").json() == []


@pytest.mark.parametrize(
    "path",
    [
        "/contracts/{id}/obligations",
        "/contracts/{id}/risks",
        "/contracts/{id}/clauses",
    ],
)
def test_related_listings_report_missing_contract(listing_api, path):
    client, _ = listing_api
    assert client.get(path.format(id=uuid4())).status_code == 404


@pytest.mark.parametrize(
    ("path", "params"),
    [
        (
            "/contracts",
            {"expiration_date_from": "2028-01-01", "expiration_date_to": "2027-01-01"},
        ),
        (
            "/contracts",
            {"renewal_date_from": "2028-01-01", "renewal_date_to": "2027-01-01"},
        ),
        ("/contracts", {"contract_type": "   "}),
        ("/contracts", {"party": "   "}),
        ("/contracts/{id}/risks", {"severity": "urgent"}),
        ("/contracts/{id}/obligations", {"priority": "urgent"}),
        ("/contracts/{id}/clauses", {"limit": 0}),
    ],
)
def test_listing_filters_are_validated(listing_api, path, params):
    client, (contract_id, _, _) = listing_api
    response = client.get(path.format(id=contract_id), params=params)
    assert response.status_code == 422
