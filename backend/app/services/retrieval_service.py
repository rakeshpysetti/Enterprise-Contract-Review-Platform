"""Build and query contract-scoped semantic indexes."""

import hashlib
import json
import uuid
from dataclasses import dataclass

from app.ai.rag.index import (
    ContractVectorIndexStore,
    VectorIndexError,
    VectorIndexMetadata,
)
from app.db.models import ContractChunk
from app.db.repositories import ContractChunkRepository, ContractRepository
from app.services.embedding_service import EmbeddingProvider
from sqlalchemy.orm import Session


class ContractNotFoundError(LookupError):
    pass


class ContractHasNoChunksError(ValueError):
    pass


class EmbeddingModelMismatchError(ValueError):
    pass


class StaleVectorIndexError(VectorIndexError):
    pass


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunk: ContractChunk
    score: float


def chunk_content_sha256(chunks: list[ContractChunk]) -> str:
    source = [{"chunk_id": str(chunk.id), "content": chunk.content} for chunk in chunks]
    encoded = json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


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
        source_sha256=chunk_content_sha256(chunks),
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
    if ContractRepository(session).get(contract_id) is None:
        raise ContractNotFoundError(f"Contract {contract_id} was not found")
    query_vector = embeddings.encode([query])[0]
    matches, metadata = index_store.search(
        contract_id=contract_id, query_vector=query_vector, top_k=top_k
    )
    if metadata.model_name != embeddings.model_name:
        raise EmbeddingModelMismatchError(
            "Query embedding model does not match the indexed model"
        )
    current_chunks = ContractChunkRepository(session).list_for_contract(contract_id)
    if {str(chunk.id) for chunk in current_chunks} != set(
        metadata.chunk_ids
    ) or chunk_content_sha256(current_chunks) != metadata.source_sha256:
        raise StaleVectorIndexError("Contract chunks changed after indexing")
    chunks_by_id = ContractChunkRepository(session).get_many_for_contract(
        contract_id, [match.chunk_id for match in matches]
    )
    if len(chunks_by_id) != len(matches):
        raise StaleVectorIndexError("Vector index references missing contract chunks")
    return [
        RetrievalResult(chunk=chunks_by_id[match.chunk_id], score=match.score)
        for match in matches
    ]
