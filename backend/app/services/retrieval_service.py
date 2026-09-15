"""Build and query contract-scoped semantic indexes."""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.rag.index import (
    ContractVectorIndexStore,
    VectorIndexError,
    VectorIndexMetadata,
)
from app.db.models import ContractChunk
from app.db.repositories import ContractChunkRepository, ContractRepository
from app.services.embedding_service import EmbeddingProvider


class ContractNotFoundError(LookupError):
    pass


class ContractHasNoChunksError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunk: ContractChunk
    score: float


def build_contract_index(
    session: Session,
    *,
    contract_id: uuid.UUID,
    embeddings: EmbeddingProvider,
    index_store: ContractVectorIndexStore,
) -> VectorIndexMetadata:
    if ContractRepository(session).get(contract_id) is None:
        raise ContractNotFoundError(f"Contract {contract_id} was not found")
    chunks = ContractChunkRepository(session).list_for_contract(contract_id)
    if not chunks:
        raise ContractHasNoChunksError("Contract does not contain any chunks")
    vectors = embeddings.encode([chunk.content for chunk in chunks])
    return index_store.write(
        contract_id=contract_id,
        model_name=embeddings.model_name,
        chunk_ids=[chunk.id for chunk in chunks],
        vectors=vectors,
    )


def retrieve_contract_chunks(
    session: Session,
    *,
    contract_id: uuid.UUID,
    query: str,
    embeddings: EmbeddingProvider,
    index_store: ContractVectorIndexStore,
    top_k: int,
) -> list[RetrievalResult]:
    if not query.strip():
        raise ValueError("A retrieval query is required")
    query_vector = embeddings.encode([query])[0]
    matches, metadata = index_store.search(
        contract_id=contract_id, query_vector=query_vector, top_k=top_k
    )
    if metadata.model_name != embeddings.model_name:
        raise ValueError("Query embedding model does not match the indexed model")
    chunks_by_id = ContractChunkRepository(session).get_many_for_contract(
        contract_id, [match.chunk_id for match in matches]
    )
    if len(chunks_by_id) != len(matches):
        raise VectorIndexError("Vector index references missing contract chunks")
    return [
        RetrievalResult(chunk=chunks_by_id[match.chunk_id], score=match.score)
        for match in matches
    ]
