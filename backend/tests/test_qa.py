import hashlib
from collections.abc import Sequence
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.rag.index import ContractVectorIndexStore
from app.ai.rag.retriever import ContractRetriever
from app.api.dependencies import get_contract_retriever, get_llm_service
from app.core.config import Settings
from app.db.database import Base, get_db, get_session_factory
from app.db.models import Contract, ContractChunk
from app.main import create_app
from app.schemas.analysis import GroundedAnswer


class DeterministicEmbeddings:
    model_name = "test/qa-embeddings"
    dimension = 16

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            vector = np.zeros(self.dimension, dtype=np.float32)
            for token in text.lower().split():
                position = int.from_bytes(
                    hashlib.sha256(token.encode()).digest()[:2], "big"
                ) % self.dimension
                vector[position] += 1
            norm = np.linalg.norm(vector)
            if norm:
                vector /= norm
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float32)


class GroundedMockLLM:
    def __init__(self, payment_chunk_id: UUID) -> None:
        self.payment_chunk_id = payment_chunk_id
        self.prompts = []
        self.invalid_citation = False

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        raise AssertionError("Plain text generation should not be used")

    def generate_structured(self, prompt, schema, *, system=None):
        self.prompts.append(prompt)
        assert schema is GroundedAnswer
        assert system is None
        if self.invalid_citation:
            return GroundedAnswer(
                answer="The invoice period is 30 days.",
                cited_chunk_ids=[uuid4()],
                confidence=0.9,
            )
        if (
            "What is the invoice payment period?" in prompt
            and str(self.payment_chunk_id) in prompt
        ):
            return GroundedAnswer(
                answer="Invoices are due within 30 days of receipt.",
                cited_chunk_ids=[self.payment_chunk_id],
                confidence=0.97,
            )
        return GroundedAnswer(answer=None, cited_chunk_ids=[], confidence=0)


@pytest.fixture
def qa_api(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        first = Contract(title="First", filename="first.pdf")
        payment = ContractChunk(
            chunk_index=0,
            page_number=4,
            content="Invoices are due within 30 days of receipt.",
        )
        first.chunks = [
            payment,
            ContractChunk(
                chunk_index=1,
                page_number=8,
                content="Either party may terminate with 60 days notice.",
            ),
        ]
        second = Contract(title="Second", filename="second.pdf")
        second.chunks = [
            ContractChunk(
                chunk_index=0,
                page_number=2,
                content="Confidential information must remain protected.",
            )
        ]
        empty = Contract(title="Empty", filename="empty.pdf")
        session.add_all([first, second, empty])
        session.commit()
        identifiers = first.id, second.id, empty.id
        payment_chunk_id = payment.id

    settings = Settings(
        _env_file=None,
        app_env="test",
        vector_index_dir=tmp_path / "indexes",
        retrieval_top_k=2,
    )
    app = create_app(settings)
    retriever = ContractRetriever(settings)
    retriever.embeddings = DeterministicEmbeddings()
    retriever.index_store = ContractVectorIndexStore(settings.vector_index_dir)
    llm = GroundedMockLLM(payment_chunk_id)

    def override_database():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_contract_retriever] = lambda: retriever
    app.dependency_overrides[get_llm_service] = lambda: llm
    with TestClient(app) as client:
        yield client, identifiers, payment_chunk_id, retriever, llm
    engine.dispose()


def test_question_answer_returns_grounded_sources_and_page_citations(qa_api):
    client, (first_id, _, _), payment_chunk_id, retriever, llm = qa_api

    response = client.post(
        f"/contracts/{first_id}/questions",
        json={"question": "What is the invoice payment period?", "top_k": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "contract_id": str(first_id),
        "question": "What is the invoice payment period?",
        "answered": True,
        "answer": "Invoices are due within 30 days of receipt.",
        "sources": [
            {
                "chunk_id": str(payment_chunk_id),
                "excerpt": "Invoices are due within 30 days of receipt.",
                "page_number": 4,
            }
        ],
        "confidence": 0.97,
    }
    assert "using only the retrieved contract context" in llm.prompts[0]
    assert f"[CHUNK {payment_chunk_id}] [PAGE 4]" in llm.prompts[0]
    assert (retriever.index_store.root / str(first_id) / "index.faiss").is_file()


def test_question_with_no_contract_answer_is_explicitly_unanswered(qa_api):
    client, (first_id, _, _), _, _, _ = qa_api
    response = client.post(
        f"/contracts/{first_id}/questions",
        json={"question": "What insurance coverage is required?"},
    )

    assert response.status_code == 200
    assert response.json()["answered"] is False
    assert response.json()["answer"] is None
    assert response.json()["sources"] == []
    assert response.json()["confidence"] == 0


def test_question_text_is_not_interpreted_as_prompt_template_syntax(qa_api):
    client, (first_id, _, _), _, _, llm = qa_api
    response = client.post(
        f"/contracts/{first_id}/questions",
        json={"question": "Does {{CONTEXT}} define insurance coverage?"},
    )

    assert response.status_code == 200
    assert response.json()["answered"] is False
    assert "Does {{CONTEXT}} define insurance coverage?" in llm.prompts[-1]


def test_question_retrieval_is_isolated_to_selected_contract(qa_api):
    client, (_, second_id, _), _, _, llm = qa_api
    response = client.post(
        f"/contracts/{second_id}/questions",
        json={"question": "What is the invoice payment period?"},
    )

    assert response.status_code == 200
    assert response.json()["answered"] is False
    assert "Confidential information" in llm.prompts[-1]
    assert "Invoices are due" not in llm.prompts[-1]


def test_invented_model_citation_is_rejected(qa_api):
    client, (first_id, _, _), _, _, llm = qa_api
    llm.invalid_citation = True

    response = client.post(
        f"/contracts/{first_id}/questions",
        json={"question": "What is the invoice payment period?"},
    )

    assert response.status_code == 502
    assert "grounded contract answer" in response.json()["detail"]


def test_question_endpoint_reports_missing_and_empty_contracts(qa_api):
    client, (_, _, empty_id), _, _, _ = qa_api
    missing = client.post(
        f"/contracts/{uuid4()}/questions",
        json={"question": "What are the payment terms?"},
    )
    empty = client.post(
        f"/contracts/{empty_id}/questions",
        json={"question": "What are the payment terms?"},
    )

    assert missing.status_code == 404
    assert empty.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "Payment?", "top_k": 0},
        {"question": "Payment?", "top_k": 101},
    ],
)
def test_question_endpoint_validates_requests(qa_api, payload):
    client, (first_id, _, _), _, _, _ = qa_api
    assert client.post(f"/contracts/{first_id}/questions", json=payload).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"answer": None, "cited_chunk_ids": [str(uuid4())], "confidence": 0},
        {"answer": None, "cited_chunk_ids": [], "confidence": 0.1},
        {"answer": "Answer", "cited_chunk_ids": [], "confidence": 0.8},
    ],
)
def test_grounded_answer_schema_rejects_inconsistent_answers(payload):
    with pytest.raises(ValidationError):
        GroundedAnswer.model_validate(payload)
