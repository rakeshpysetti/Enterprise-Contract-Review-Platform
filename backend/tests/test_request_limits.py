from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.db.database import get_db
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def limited_client():
    app = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            max_pdf_size_bytes=1024,
            max_request_body_bytes=1024,
            cors_origins=["https://contracts.example.com"],
        )
    )
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(info={})
    with TestClient(app) as client:
        yield client


def test_declared_upload_size_is_rejected_before_parsing(limited_client):
    response = limited_client.post(
        "/contracts", content=b"", headers={"Content-Length": "3000"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"
    assert response.headers["X-Request-ID"]


def test_body_limit_errors_keep_allowed_cors_headers(limited_client):
    response = limited_client.post(
        "/contracts",
        content=b"",
        headers={"Content-Length": "3000", "Origin": "https://contracts.example.com"},
    )
    assert response.status_code == 413
    assert (
        response.headers["Access-Control-Allow-Origin"]
        == "https://contracts.example.com"
    )


def test_chunked_multipart_body_cannot_bypass_request_limit(limited_client):
    def body():
        yield (
            b'--limit-test\r\nContent-Disposition: form-data; name="file"; '
            b'filename="large.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
        )
        yield b"%PDF-" + b"x" * 2200
        yield b"\r\n--limit-test--\r\n"

    response = limited_client.post(
        "/contracts",
        content=body(),
        headers={"Content-Type": "multipart/form-data; boundary=limit-test"},
    )
    assert response.status_code == 413
    assert "configured size limit" in response.json()["detail"]


def test_json_body_uses_smaller_limit(limited_client):
    response = limited_client.post(
        "/contracts/00000000-0000-0000-0000-000000000000/questions",
        content=b"x" * 1025,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_invalid_content_length_is_rejected(limited_client):
    response = limited_client.post(
        "/contracts", content=b"", headers={"Content-Length": "-1"}
    )
    assert response.status_code == 400
