import hashlib
from collections.abc import Sequence
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.ai.rag.index import ContractVectorIndexStore
from app.ai.rag.retriever import ContractRetriever
from app.api.dependencies import get_contract_retriever
from app.core.config import Settings
from app.db.database import Base, get_db, get_session_factory
from app.db.models import Contract, ContractChunk
from app.main import create_app


class DeterministicEmbeddings:
    model_name = "test/search-embeddings"
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


@pytest.fixture
def search_api(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        first = Contract(title="First", filename="first.pdf")
        first.chunks = [
            ContractChunk(
                chunk_index=0, page_number=4, content="payment invoice fees"
            ),
            ContractChunk(
                chunk_index=1, page_number=9, content="termination notice period"
            ),
        ]
        second = Contract(title="Second", filename="second.pdf")
        second.chunks = [
            ContractChunk(
                chunk_index=0, page_number=2, content="termination notice period"
            )
        ]
        empty = Contract(title="Empty", filename="empty.pdf")
        session.add_all([first, second, empty])
        session.commit()
        identifiers = first.id, second.id, empty.id

    settings = Settings(
        _env_file=None,
        app_env="test",
        vector_index_dir=tmp_path / "indexes",
        retrieval_top_k=1,
    )
    app = create_app(settings)
    retriever = ContractRetriever(settings)
    retriever.embeddings = DeterministicEmbeddings()
    retriever.index_store = ContractVectorIndexStore(settings.vector_index_dir)

    def override_database():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_contract_retriever] = lambda: retriever
    with TestClient(app) as client:
        yield client, identifiers, retriever
    engine.dispose()


def test_search_returns_text_page_score_and_builds_index(search_api):
    client, (first_id, _, _), retriever = search_api
    response = client.post(
        f"/contracts/{first_id}/search",
        json={"query": "termination notice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contract_id"] == str(first_id)
    assert body["query"] == "termination notice"
    assert len(body["results"]) == 1
    assert body["results"][0]["text"] == "termination notice period"
    assert body["results"][0]["page_number"] == 9
    assert -1 <= body["results"][0]["similarity_score"] <= 1
    assert (retriever.index_store.root / str(first_id) / "index.faiss").is_file()


def test_search_top_k_and_contract_isolation(search_api):
    client, (first_id, second_id, _), _ = search_api
    first = client.post(
        f"/contracts/{first_id}/search",
        json={"query": "termination notice", "top_k": 10},
    )
    second = client.post(
        f"/contracts/{second_id}/search",
        json={"query": "termination notice", "top_k": 10},
    )
    assert len(first.json()["results"]) == 2
    assert len(second.json()["results"]) == 1
    assert {result["page_number"] for result in first.json()["results"]} == {4, 9}
    assert {result["page_number"] for result in second.json()["results"]} == {2}


def test_search_reports_missing_and_empty_contracts(search_api):
    client, (_, _, empty_id), _ = search_api
    assert client.post(
        f"/contracts/{uuid4()}/search", json={"query": "payment"}
    ).status_code == 404
    response = client.post(
        f"/contracts/{empty_id}/search", json={"query": "payment"}
    )
    assert response.status_code == 409
    assert "does not contain any chunks" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "payment", "top_k": 0},
        {"query": "payment", "top_k": 101},
    ],
)
def test_search_validates_request(search_api, payload):
    client, (first_id, _, _), _ = search_api
    assert client.post(
        f"/contracts/{first_id}/search", json=payload
    ).status_code == 422
