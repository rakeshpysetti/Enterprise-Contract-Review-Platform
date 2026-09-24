import hashlib
from collections.abc import Sequence
from io import BytesIO
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app.ai.rag.index import ContractVectorIndexStore
from app.ai.rag.retriever import ContractRetriever
from app.api.dependencies import get_contract_retriever, get_llm_service
from app.core.config import Settings
from app.db.database import Base, get_db, get_session_factory
from app.db.models import Clause, Contract, ContractStatus, Obligation, Risk, RiskLevel
from app.main import create_app
from app.schemas.clause import ClauseDetection, ClauseType, DetectedClause
from app.schemas.contract import ContractMetadata, ContractParty
from app.schemas.obligation import (
    ExtractedObligation,
    ObligationExtraction,
)
from app.schemas.risk import ExtractedRisk, RiskExtraction
from app.db.models import ObligationPriority


class CountingEmbeddings:
    model_name = "test/analysis-embeddings"
    dimension = 8

    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        self.calls += 1
        vectors = []
        for text in texts:
            vector = np.zeros(self.dimension, dtype=np.float32)
            digest = hashlib.sha256(text.encode()).digest()
            for index, value in enumerate(digest[: self.dimension]):
                vector[index] = value + 1
            vector /= np.linalg.norm(vector)
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float32)


class StructuredAnalysisLLM:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        raise AssertionError("Plain text generation should not be used")

    def generate_structured(self, prompt, schema, *, system=None):
        self.calls.append(schema)
        if self.fail:
            raise RuntimeError("model unavailable")
        if schema is ContractMetadata:
            return ContractMetadata(
                title="Master Services Agreement",
                contract_type="MSA",
                parties=[ContractParty(name="Customer", role="customer")],
                payment_terms="Invoices are due within 30 days.",
            )
        if schema is ObligationExtraction:
            return ObligationExtraction(
                obligations=[
                    ExtractedObligation(
                        title="Pay invoices",
                        description="Customer must pay invoices within 30 days.",
                        responsible_party="Customer",
                        counterparty="Provider",
                        recurring_frequency="within 30 days after each invoice",
                        priority=ObligationPriority.high,
                        source_text="Customer shall pay invoices within 30 days.",
                        page_number=1,
                        confidence=0.97,
                    )
                ]
            )
        if schema is ClauseDetection:
            return ClauseDetection(
                clauses=[
                    DetectedClause(
                        clause_type=ClauseType.payment,
                        source_text="Customer shall pay invoices within 30 days.",
                        page_number=1,
                        confidence=0.96,
                    )
                ]
            )
        if schema is RiskExtraction:
            return RiskExtraction(
                risks=[
                    ExtractedRisk(
                        category="Liability",
                        description="Liability is stated as unlimited.",
                        level=RiskLevel.high,
                        why_it_matters="This may create substantial exposure.",
                        recommendation="Consider reviewing an appropriate liability cap.",
                        source_text="Supplier liability is unlimited.",
                        page_number=1,
                        confidence=0.95,
                    )
                ]
            )
        raise AssertionError(f"Unexpected schema: {schema}")


def make_pdf(text: str) -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    for line_number, line in enumerate(text.split("\n")):
        canvas.drawString(72, 750 - line_number * 16, line)
    canvas.save()
    return output.getvalue()


@pytest.fixture
def analysis_api(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)
    settings = Settings(
        _env_file=None,
        app_env="test",
        vector_index_dir=tmp_path / "indexes",
    )
    app = create_app(settings)
    llm = StructuredAnalysisLLM()
    retriever = ContractRetriever(settings)
    embeddings = CountingEmbeddings()
    retriever.embeddings = embeddings
    retriever.index_store = ContractVectorIndexStore(settings.vector_index_dir)

    def override_database():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_llm_service] = lambda: llm
    app.dependency_overrides[get_contract_retriever] = lambda: retriever
    with TestClient(app) as client:
        yield client, session_factory, app, llm, retriever, embeddings
    engine.dispose()


def upload_contract(client: TestClient) -> dict:
    text = "\n".join(
        [
            "MASTER SERVICES AGREEMENT",
            "Customer shall pay invoices within 30 days.",
            "Supplier liability is unlimited.",
        ]
    )
    response = client.post(
        "/contracts",
        files={"file": ("agreement.pdf", make_pdf(text), "application/pdf")},
    )
    assert response.status_code == 201
    return response.json()


def test_analysis_endpoint_runs_and_persists_complete_workflow(analysis_api):
    client, session_factory, _, llm, retriever, embeddings = analysis_api
    uploaded = upload_contract(client)
    assert uploaded["status"] == ContractStatus.pending.value

    response = client.post(f"/contracts/{uploaded['id']}/analyze")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ContractStatus.completed.value
    assert body["analysis_reused"] is False
    assert body["title"] == "Master Services Agreement"
    assert body["contract_type"] == "MSA"
    assert len(body["obligations"]) == 1
    assert body["clauses"][0]["clause_type"] == ClauseType.payment.value
    assert len(body["risks"]) == 1
    assert llm.calls == [
        ContractMetadata,
        ObligationExtraction,
        ClauseDetection,
        RiskExtraction,
    ]
    assert embeddings.calls == 1
    assert (
        retriever.index_store.root / uploaded["id"] / "index.faiss"
    ).is_file()

    with session_factory() as session:
        contract_id = UUID(body["id"])
        contract = session.get(Contract, contract_id)
        assert contract is not None
        assert contract.status is ContractStatus.completed
        assert session.scalar(select(Obligation)).contract_id == contract.id
        assert session.scalar(select(Clause)).contract_id == contract.id
        assert session.scalar(select(Risk)).contract_id == contract.id


def test_completed_analysis_is_reused_without_duplicate_work(analysis_api):
    client, session_factory, _, llm, _, embeddings = analysis_api
    uploaded = upload_contract(client)
    first = client.post(f"/contracts/{uploaded['id']}/analyze")
    call_count = len(llm.calls)

    second = client.post(f"/contracts/{uploaded['id']}/analyze")

    assert first.status_code == second.status_code == 200
    assert second.json()["analysis_reused"] is True
    assert len(llm.calls) == call_count
    assert embeddings.calls == 1
    with session_factory() as session:
        assert len(list(session.scalars(select(Obligation)))) == 1
        assert len(list(session.scalars(select(Clause)))) == 1
        assert len(list(session.scalars(select(Risk)))) == 1


def test_failed_analysis_sets_failed_state_and_can_be_retried(analysis_api):
    client, session_factory, app, _, _, _ = analysis_api
    uploaded = upload_contract(client)
    failing = StructuredAnalysisLLM(fail=True)
    app.dependency_overrides[get_llm_service] = lambda: failing

    failed = client.post(f"/contracts/{uploaded['id']}/analyze")

    assert failed.status_code == 502
    assert client.get(f"/contracts/{uploaded['id']}").json()["status"] == "failed"
    with session_factory() as session:
        assert session.scalar(select(Obligation)) is None
        assert session.scalar(select(Clause)) is None
        assert session.scalar(select(Risk)) is None

    working = StructuredAnalysisLLM()
    app.dependency_overrides[get_llm_service] = lambda: working
    retried = client.post(f"/contracts/{uploaded['id']}/analyze")
    assert retried.status_code == 200
    assert retried.json()["status"] == "completed"


def test_analysis_rejects_missing_and_processing_contracts(analysis_api):
    client, session_factory, _, _, _, _ = analysis_api
    assert client.post(f"/contracts/{uuid4()}/analyze").status_code == 404
    with session_factory() as session:
        contract = Contract(
            title="Processing",
            filename="processing.pdf",
            status=ContractStatus.processing,
        )
        session.add(contract)
        session.commit()
        contract_id = contract.id

    response = client.post(f"/contracts/{contract_id}/analyze")
    assert response.status_code == 409
    assert "already in progress" in response.json()["detail"]
