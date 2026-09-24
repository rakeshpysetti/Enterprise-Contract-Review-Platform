"""Configured semantic retrieval facade."""

import uuid

from sqlalchemy.orm import Session

from app.ai.rag.index import (
    ContractVectorIndexStore,
    VectorIndexError,
    VectorIndexMetadata,
    VectorIndexNotFoundError,
)
from app.core.config import Settings
from app.db.repositories import ContractChunkRepository, ContractRepository
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.retrieval_service import (
    ContractHasNoChunksError,
    ContractNotFoundError,
    RetrievalResult,
    EmbeddingModelMismatchError,
    StaleVectorIndexError,
    build_contract_index,
    retrieve_contract_chunks,
)


class ContractRetriever:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.embeddings = HuggingFaceEmbeddingService(
            self.settings.embedding_model, device=self.settings.embedding_device
        )
        self.index_store = ContractVectorIndexStore(self.settings.vector_index_dir)

    def index_contract(
        self, session: Session, contract_id: uuid.UUID
    ) -> VectorIndexMetadata:
        return build_contract_index(
            session,
            contract_id=contract_id,
            embeddings=self.embeddings,
            index_store=self.index_store,
        )

    def ensure_index(
        self, session: Session, contract_id: uuid.UUID
    ) -> VectorIndexMetadata:
        if ContractRepository(session).get(contract_id) is None:
            raise ContractNotFoundError(f"Contract {contract_id} was not found")
        chunks = ContractChunkRepository(session).list_for_contract(contract_id)
        if not chunks:
            raise ContractHasNoChunksError("Contract does not contain any chunks")
        expected_ids = {str(chunk.id) for chunk in chunks}
        try:
            _, metadata = self.index_store.load(contract_id)
            if (
                metadata.model_name == self.embeddings.model_name
                and set(metadata.chunk_ids) == expected_ids
                and metadata.vector_count == len(chunks)
            ):
                return metadata
        except VectorIndexError:
            pass
        return self.index_contract(session, contract_id)

    def retrieve(
        self,
        session: Session,
        contract_id: uuid.UUID,
        query: str,
        *,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        result_count = top_k if top_k is not None else self.settings.retrieval_top_k
        try:
            return retrieve_contract_chunks(
                session,
                contract_id=contract_id,
                query=query,
                embeddings=self.embeddings,
                index_store=self.index_store,
                top_k=result_count,
            )
        except (
            VectorIndexNotFoundError,
            EmbeddingModelMismatchError,
            StaleVectorIndexError,
        ):
            self.index_contract(session, contract_id)
            return retrieve_contract_chunks(
                session,
                contract_id=contract_id,
                query=query,
                embeddings=self.embeddings,
                index_store=self.index_store,
                top_k=result_count,
            )
