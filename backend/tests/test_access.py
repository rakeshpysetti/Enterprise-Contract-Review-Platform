import hashlib
from io import BytesIO
from uuid import UUID

import pytest
from app.core.config import Settings
from app.db.database import Base, get_db, get_session_factory
from app.db.models import Contract, ContractStatus
from app.main import create_app
from fastapi.testclient import TestClient
from pydantic import ValidationError
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
def secured_api():
    accounts = [
        {
            "user_id": user,
            "tenant_id": tenant,
            "role": role,
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        }
        for user, tenant, role, token in [
            ("alice", "north", "reviewer", "alice-secret"),
            ("bob", "south", "reviewer", "bob-secret"),
            ("reader", "north", "reader", "reader-secret"),
        ]
    ]
    app = create_app(
        Settings(_env_file=None, app_env="production", auth_accounts=accounts)
    )
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        north = Contract(title="North", filename="north.pdf", tenant_id="north")
        south = Contract(title="South", filename="south.pdf", tenant_id="south")
        legacy = Contract(title="Unassigned", filename="legacy.pdf")
        session.add_all([north, south, legacy])
        session.commit()
        ids = [str(north.id), str(south.id), str(legacy.id)]

    def database():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, factory, ids
    engine.dispose()


def auth(token="alice-secret"):
    return {"Authorization": f"Bearer {token}"}


def test_authentication_and_identity(secured_api):
    client, _, _ = secured_api
    for headers in [{}, auth("wrong"), {"Authorization": "Basic abc"}]:
        response = client.get("/contracts", headers=headers)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
    identity = client.get("/auth/me", headers=auth())
    assert identity.json() == {
        "user_id": "alice",
        "tenant_id": "north",
        "role": "reviewer",
        "authentication_required": True,
    }
    assert "secret" not in identity.text and "sha256" not in identity.text
    assert identity.headers["Cache-Control"] == "no-store"


def test_lists_and_all_contract_routes_hide_other_tenants(secured_api):
    client, _, (north, south, legacy) = secured_api
    assert [row["id"] for row in client.get("/contracts", headers=auth()).json()] == [
        north
    ]
    assert [
        row["id"] for row in client.get("/contracts", headers=auth("bob-secret")).json()
    ] == [south]
    for contract_id in [south, legacy]:
        for suffix in ["", "/summary", "/obligations", "/risks", "/clauses"]:
            assert (
                client.get(
                    f"/contracts/{contract_id}{suffix}", headers=auth()
                ).status_code
                == 404
            )
        for suffix, payload in [
            ("analyze", {}),
            ("recover", {}),
            ("search", {"query": "terms"}),
            ("questions", {"question": "Payment?"}),
        ]:
            assert (
                client.post(
                    f"/contracts/{contract_id}/{suffix}", headers=auth(), json=payload
                ).status_code
                == 404
            )
    assert client.get(f"/contracts/{north}", headers=auth()).status_code == 200


def test_reader_cannot_mutate_but_can_read_and_search(secured_api):
    client, factory, (north, _, _) = secured_api
    headers = auth("reader-secret")
    for path in [
        "/contracts",
        f"/contracts/{north}/analyze",
        f"/contracts/{north}/recover",
    ]:
        assert client.post(path, headers=headers).status_code == 403
    assert client.get(f"/contracts/{north}/summary", headers=headers).status_code == 200
    assert (
        client.post(
            f"/contracts/{north}/search", headers=headers, json={"query": "terms"}
        ).status_code
        == 409
    )
    with factory() as session:
        assert session.get(Contract, UUID(north)).status == ContractStatus.pending


def test_upload_ownership_comes_from_credentials(secured_api):
    client, factory, _ = secured_api
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 750, "An agreement for the authenticated tenant.")
    canvas.save()
    response = client.post(
        "/contracts",
        headers=auth(),
        data={"tenant_id": "south"},
        files={"file": ("contract.pdf", output.getvalue(), "application/pdf")},
    )
    assert response.status_code == 201
    identifier = response.json()["id"]
    assert (
        client.get(f"/contracts/{identifier}", headers=auth("bob-secret")).status_code
        == 404
    )
    with factory() as session:
        assert session.get(Contract, UUID(identifier)).tenant_id == "north"


def test_production_fails_closed_and_ui_remains_public():
    with TestClient(
        create_app(Settings(_env_file=None, app_env="production"))
    ) as client:
        assert client.get("/contracts").status_code == 503
        assert client.get("/auth/me").status_code == 503
        response = client.get("/")
        assert response.status_code == 200
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/health").status_code == 200


def test_account_configuration_rejects_ambiguous_or_invalid_keys():
    account = {
        "user_id": "alice",
        "tenant_id": "north",
        "role": "reviewer",
        "token_sha256": hashlib.sha256(b"key").hexdigest(),
    }
    with pytest.raises(ValidationError, match="exactly one account"):
        Settings(
            _env_file=None, auth_accounts=[account, {**account, "tenant_id": "south"}]
        )
    with pytest.raises(ValidationError, match="SHA-256"):
        Settings(_env_file=None, auth_accounts=[{**account, "token_sha256": "invalid"}])
