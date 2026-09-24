from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.database import Base, get_db, get_session_factory
from app.db.models import Contract, ContractChunk, ContractStatus
from app.main import create_app


def make_pdf(*pages: str) -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    for index, text in enumerate(pages):
        for line_number, line in enumerate(text.split("\n")):
            canvas.drawString(72, 750 - line_number * 16, line)
        if index < len(pages) - 1:
            canvas.showPage()
    canvas.save()
    return output.getvalue()


@pytest.fixture
def api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)
    app = create_app(Settings(_env_file=None, app_env="test", max_pdf_size_bytes=4096))

    def override_database():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    with TestClient(app) as client:
        yield client, session_factory
    engine.dispose()


def test_upload_extracts_clean_text_and_preserves_page_numbers(api):
    client, session_factory = api
    pdf = make_pdf("First   page\nPayment terms", "Second page\nNotice clause")
    response = client.post(
        "/contracts",
        data={"title": "Service Agreement"},
        files={"file": ("agreement.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Service Agreement"
    assert body["filename"] == "agreement.pdf"
    assert body["status"] == ContractStatus.pending.value
    assert [chunk["page_number"] for chunk in body["chunks"]] == [1, 2]
    assert body["chunks"][0]["content"] == "First page\nPayment terms"

    with session_factory() as session:
        assert session.scalar(select(Contract)).id.hex == body["id"].replace("-", "")
        chunks = list(session.scalars(select(ContractChunk).order_by(ContractChunk.chunk_index)))
        assert [(chunk.chunk_index, chunk.page_number) for chunk in chunks] == [(0, 1), (1, 2)]


def test_upload_removes_client_path_from_filename(api):
    client, _ = api
    response = client.post(
        "/contracts",
        files={
            "file": (
                "C:\\fakepath\\contract.pdf",
                make_pdf("Contract text"),
                "application/pdf; charset=binary",
            )
        },
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "contract.pdf"


def test_list_and_detail_endpoints(api):
    client, _ = api
    created = client.post(
        "/contracts",
        files={"file": ("contract.pdf", make_pdf("Contract text"), "application/pdf")},
    ).json()

    listed = client.get("/contracts")
    detail = client.get(f"/contracts/{created['id']}")
    missing = client.get(f"/contracts/{uuid4()}")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created["id"]]
    assert detail.status_code == 200
    assert detail.json()["chunks"][0]["page_number"] == 1
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "message"),
    [
        ("contract.txt", "application/pdf", b"not-pdf", ".pdf"),
        ("contract.pdf", "text/plain", b"%PDF-invalid", "media type"),
        ("contract.pdf", "application/pdf", b"not-pdf", "signature"),
        ("contract.pdf", "application/pdf", b"%PDF-invalid", "damaged"),
    ],
)
def test_upload_rejects_invalid_files(api, filename, content_type, data, message):
    client, session_factory = api
    response = client.post(
        "/contracts", files={"file": (filename, data, content_type)}
    )
    assert response.status_code == 422
    assert message in response.json()["detail"]
    with session_factory() as session:
        assert session.scalar(select(Contract)) is None


def test_upload_rejects_oversized_pdf(api):
    client, _ = api
    response = client.post(
        "/contracts",
        files={"file": ("large.pdf", b"%PDF-" + b"x" * 4096, "application/pdf")},
    )
    assert response.status_code == 413


def test_upload_rejects_textless_pdf(api):
    client, _ = api
    response = client.post(
        "/contracts",
        files={"file": ("blank.pdf", make_pdf(""), "application/pdf")},
    )
    assert response.status_code == 422
    assert "extractable text" in response.json()["detail"]
