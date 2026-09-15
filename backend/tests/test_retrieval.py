import hashlib
import json
from collections.abc import Sequence

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.rag.index import ContractVectorIndexStore, VectorIndexError
from app.ai.rag.retriever import ContractRetriever
from app.core.config import Settings
from app.db.database import Base, get_session_factory
from app.db.models import Contract, ContractChunk
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.retrieval_service import (
    build_contract_index,
    retrieve_contract_chunks,
)


class DeterministicEmbeddings:
    model_name = "test/hash-embeddings"
    dimension = 8

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            vector = np.zeros(self.dimension, dtype=np.float32)
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode()).digest()
                vector[int.from_bytes(digest[:2], "big") % self.dimension] += 1
            norm = np.linalg.norm(vector)
            if norm:
                vector /= norm
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float32)


@pytest.fixture
def retrieval_context(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with get_session_factory(engine)() as session:
        first = Contract(title="First", filename="first.pdf")
        first.chunks = [
            ContractChunk(chunk_index=0, page_number=1, content="payment invoice fees"),
            ContractChunk(chunk_index=1, page_number=2, content="termination notice period"),
            ContractChunk(chunk_index=2, page_number=3, content="confidential information"),
        ]
        second = Contract(title="Second", filename="second.pdf")
        second.chunks = [
            ContractChunk(chunk_index=0, page_number=1, content="payment invoice fees"),
        ]
        session.add_all([first, second])
        session.commit()
        yield session, first, second, ContractVectorIndexStore(tmp_path / "indexes")
    engine.dispose()


def test_hugging_face_service_normalizes_and_validates_model_output():
    service = HuggingFaceEmbeddingService("test-model")

    class FakeModel:
        def encode(self, texts, **kwargs):
            assert kwargs["normalize_embeddings"] is True
            return np.asarray([[3.0, 4.0] for _ in texts])

    service.__dict__["model"] = FakeModel()
    vectors = service.encode(["one", "two"])
    assert vectors.dtype == np.float32
    assert vectors.shape == (2, 2)


def test_build_persists_faiss_index_and_metadata(retrieval_context):
    session, first, _, store = retrieval_context
    metadata = build_contract_index(
        session,
        contract_id=first.id,
        embeddings=DeterministicEmbeddings(),
        index_store=store,
    )
    index, loaded = store.load(first.id)

    assert index.ntotal == len(first.chunks)
    assert loaded == metadata
    assert loaded.chunk_ids == [str(chunk.id) for chunk in first.chunks]
    persisted = json.loads(
        (store.root / str(first.id) / "metadata.json").read_text(encoding="utf-8")
    )
    assert persisted["contract_id"] == str(first.id)
    assert persisted["metric"] == "cosine"


def test_retrieval_maps_results_and_honors_top_k(retrieval_context):
    session, first, _, store = retrieval_context
    embeddings = DeterministicEmbeddings()
    build_contract_index(
        session, contract_id=first.id, embeddings=embeddings, index_store=store
    )

    results = retrieve_contract_chunks(
        session,
        contract_id=first.id,
        query="termination notice",
        embeddings=embeddings,
        index_store=store,
        top_k=2,
    )
    assert len(results) == 2
    assert results[0].chunk.content == "termination notice period"
    assert all(result.chunk.contract_id == first.id for result in results)


def test_retrieval_is_isolated_to_selected_contract(retrieval_context):
    session, first, second, store = retrieval_context
    embeddings = DeterministicEmbeddings()
    build_contract_index(
        session, contract_id=first.id, embeddings=embeddings, index_store=store
    )
    build_contract_index(
        session, contract_id=second.id, embeddings=embeddings, index_store=store
    )

    first_results = retrieve_contract_chunks(
        session,
        contract_id=first.id,
        query="payment invoice fees",
        embeddings=embeddings,
        index_store=store,
        top_k=10,
    )
    second_results = retrieve_contract_chunks(
        session,
        contract_id=second.id,
        query="payment invoice fees",
        embeddings=embeddings,
        index_store=store,
        top_k=10,
    )
    assert {result.chunk.contract_id for result in first_results} == {first.id}
    assert {result.chunk.contract_id for result in second_results} == {second.id}
    assert len(second_results) == 1


def test_index_checksum_detects_tampering(retrieval_context):
    session, first, _, store = retrieval_context
    build_contract_index(
        session,
        contract_id=first.id,
        embeddings=DeterministicEmbeddings(),
        index_store=store,
    )
    index_path = store.root / str(first.id) / "index.faiss"
    index_path.write_bytes(index_path.read_bytes() + b"tampered")
    with pytest.raises(VectorIndexError, match="checksum"):
        store.load(first.id)


def test_retrieval_rejects_different_embedding_model(retrieval_context):
    session, first, _, store = retrieval_context
    embeddings = DeterministicEmbeddings()
    build_contract_index(
        session, contract_id=first.id, embeddings=embeddings, index_store=store
    )
    embeddings.model_name = "different/model"
    with pytest.raises(ValueError, match="does not match"):
        retrieve_contract_chunks(
            session,
            contract_id=first.id,
            query="payment",
            embeddings=embeddings,
            index_store=store,
            top_k=1,
        )


def test_retriever_uses_configured_top_k_and_rejects_zero(retrieval_context):
    session, first, _, store = retrieval_context
    embeddings = DeterministicEmbeddings()
    build_contract_index(
        session, contract_id=first.id, embeddings=embeddings, index_store=store
    )
    retriever = ContractRetriever(
        Settings(_env_file=None, retrieval_top_k=2, vector_index_dir=store.root)
    )
    retriever.embeddings = embeddings
    retriever.index_store = store
    assert len(retriever.retrieve(session, first.id, "payment")) == 2
    with pytest.raises(ValueError, match="top_k"):
        retriever.retrieve(session, first.id, "payment", top_k=0)
