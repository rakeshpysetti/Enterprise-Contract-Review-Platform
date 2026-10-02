import asyncio
import io
import json
import logging
import tempfile

import pytest
from app.core.config import Settings
from app.core.logging import configure_logging
from app.main import create_app
from app.services import document_service
from app.services.document_service import (
    InvalidPDFError,
    UploadTooLargeError,
    read_upload_safely,
    validate_pdf,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError


class FakeUpload:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0
        self.read_sizes = []
        self.closed = False

    async def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        chunk = self.data[self.position : self.position + size]
        self.position += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


def test_request_and_correlation_ids_are_returned_and_propagated():
    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        generated = client.get("/health")
        supplied = client.get(
            "/health",
            headers={
                "X-Request-ID": "request-123",
                "X-Correlation-ID": "workflow-456",
            },
        )

    assert generated.headers["X-Request-ID"]
    assert generated.headers["X-Correlation-ID"] == generated.headers["X-Request-ID"]
    assert supplied.headers["X-Request-ID"] == "request-123"
    assert supplied.headers["X-Correlation-ID"] == "workflow-456"


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Request-ID": "bad id with spaces"},
        {"X-Correlation-ID": "bad@correlation"},
        {"X-Request-ID": "x" * 129},
    ],
)
def test_invalid_request_context_headers_are_rejected(headers):
    with TestClient(create_app(Settings(_env_file=None, app_env="test"))) as client:
        response = client.get("/health", headers=headers)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request_header"
    assert response.headers["X-Request-ID"]


def test_http_and_validation_errors_use_centralized_safe_shape():
    with TestClient(create_app(Settings(_env_file=None, app_env="test"))) as client:
        missing = client.get("/not-a-real-route")
        invalid = client.get("/contracts/not-a-uuid")

    assert missing.status_code == 404
    assert missing.json()["detail"] == "Not Found"
    assert missing.json()["error"]["code"] == "http_404"
    assert missing.json()["error"]["request_id"] == missing.headers["X-Request-ID"]
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Request validation failed"
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid.json()["error"]["details"][0]["location"] == [
        "path",
        "contract_id",
    ]
    assert "not-a-uuid" not in json.dumps(invalid.json())


def test_unhandled_errors_return_generic_response_without_leaking_content(capsys):
    app = create_app(Settings(_env_file=None, app_env="test"))

    @app.get("/failure-test")
    def fail():
        raise RuntimeError(
            "confidential contract sentence password=do-not-log token=also-secret"
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/failure-test?question=private-contract-content")

    captured = capsys.readouterr().err
    assert response.status_code == 500
    assert response.json()["detail"] == "An unexpected server error occurred"
    assert response.json()["error"]["code"] == "internal_server_error"
    assert "confidential contract sentence" not in response.text
    assert "confidential contract sentence" not in captured
    assert "private-contract-content" not in captured
    assert "do-not-log" not in captured
    assert '"route":"/failure-test"' in captured
    assert '"error_type":"RuntimeError"' in captured


def test_structured_logging_redacts_secrets_and_contract_content():
    output = io.StringIO()
    logger = configure_logging(stream=output)
    logger.info(
        "connection postgresql://user:db-password@db/contracts "
        "Bearer access-token password=plain-secret",
        extra={
            "database_url": "postgresql://user:db-password@db/contracts",
            "authorization": "Bearer access-token",
            "contract_text": "Confidential agreement language",
            "nested": {"token": "nested-token", "safe": "value"},
            "access_token": "compound-token",
            "client_secret": "compound-secret",
        },
    )

    payload = json.loads(output.getvalue())
    serialized = json.dumps(payload)
    assert payload["database_url"] == "***"
    assert payload["authorization"] == "***"
    assert payload["contract_text"] == "***"
    assert payload["nested"] == {"token": "***", "safe": "value"}
    assert payload["access_token"] == "***"
    assert payload["client_secret"] == "***"
    assert "db-password" not in serialized
    assert "access-token" not in serialized
    assert "plain-secret" not in serialized
    assert "Confidential agreement language" not in serialized
    assert logging.getLogger("uvicorn.access").disabled is True


def test_cors_is_configured_from_settings():
    app = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            cors_origins=["https://contracts.example.com"],
        )
    )
    with TestClient(app) as client:
        allowed = client.options(
            "/contracts",
            headers={
                "Origin": "https://contracts.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Request-ID",
            },
        )
        denied = client.options(
            "/contracts",
            headers={
                "Origin": "https://untrusted.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == (
        "https://contracts.example.com"
    )
    assert "x-request-id" in allowed.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in denied.headers


def test_cors_environment_parsing_and_validation(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        'CORS_ORIGINS=["https://one.example.com","https://two.example.com/"]\n'
        "CORS_ALLOW_CREDENTIALS=true\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=dotenv)
    assert settings.cors_origins == [
        "https://one.example.com",
        "https://two.example.com",
    ]
    assert settings.cors_allow_credentials is True
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            cors_origins=["*"],
            cors_allow_credentials=True,
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=["https://user:pass@example.com/path"])


def test_upload_stream_uses_closed_spooled_temporary_file(monkeypatch):
    created = []

    def tracked_spool(*args, **kwargs):
        temporary = tempfile.SpooledTemporaryFile(*args, **kwargs)
        created.append(temporary)
        return temporary

    monkeypatch.setattr(document_service, "SpooledTemporaryFile", tracked_spool)
    upload = FakeUpload(b"abcdef")

    result = asyncio.run(
        read_upload_safely(upload, max_size_bytes=10, chunk_size=2)  # type: ignore[arg-type]
    )

    assert result == b"abcdef"
    assert upload.read_sizes == [2, 2, 2, 2]
    assert upload.closed is True
    assert created[0].closed is True


def test_upload_stream_enforces_limit_and_always_closes():
    upload = FakeUpload(b"123456")

    with pytest.raises(UploadTooLargeError, match="5-byte"):
        asyncio.run(
            read_upload_safely(upload, max_size_bytes=5, chunk_size=2)  # type: ignore[arg-type]
        )

    assert upload.closed is True


@pytest.mark.parametrize(
    ("filename", "content_type", "message"),
    [
        ("contract.pdf", None, "media type"),
        ("bad\nname.pdf", "application/pdf", ".pdf"),
        ("x" * 252 + ".pdf", "application/pdf", ".pdf"),
    ],
)
def test_uploaded_filename_and_media_type_are_strictly_validated(
    filename, content_type, message
):
    with pytest.raises(InvalidPDFError, match=message):
        validate_pdf(
            filename=filename,
            content_type=content_type,
            data=b"%PDF-placeholder",
        )
