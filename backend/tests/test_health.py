from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_without_external_services():
    settings = Settings(_env_file=None, app_env="test", database_url=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"


def test_health_is_documented():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        schema = client.get("/openapi.json").json()
    assert "200" in schema["paths"]["/health"]["get"]["responses"]
