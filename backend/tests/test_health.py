from unittest.mock import Mock

import httpx
import pytest
from app.api.routes import health as health_routes
from app.core.config import Settings
from app.db.database import Base, get_db, get_session_factory
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


def test_health_without_external_services():
    settings = Settings(_env_file=None, app_env="test")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"


def test_health_is_documented():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        schema = client.get("/openapi.json").json()
    assert "200" in schema["paths"]["/health"]["get"]["responses"]


@pytest.fixture
def readiness_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)
    app = create_app(Settings(_env_file=None, app_env="test"))

    def override_database():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    response = Mock()
    response.raise_for_status.return_value = None
    monkeypatch.setattr(health_routes.httpx, "get", Mock(return_value=response))
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_readiness_verifies_database_and_ollama(readiness_client):
    response = readiness_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {"database": "ok", "ollama": "ok"},
    }
    health_routes.httpx.get.assert_called_once_with(
        "http://localhost:11434/api/tags", timeout=5.0
    )


def test_readiness_reports_unavailable_ollama(readiness_client, monkeypatch):
    monkeypatch.setattr(
        health_routes.httpx,
        "get",
        Mock(side_effect=httpx.ConnectError("unavailable")),
    )

    response = readiness_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "services": {"database": "ok", "ollama": "unavailable"},
    }
