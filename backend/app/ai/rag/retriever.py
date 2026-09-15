"""Configured semantic retrieval facade."""

import uuid

from sqlalchemy.orm import Session

from app.ai.rag.index import ContractVectorIndexStore, VectorIndexMetadata
from app.core.config import Settings
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.retrieval_service import (
    RetrievalResult,
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

    def retrieve(
        self,
        session: Session,
        contract_id: uuid.UUID,
        query: str,
        *,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        return retrieve_contract_chunks(
            session,
            contract_id=contract_id,
            query=query,
            embeddings=self.embeddings,
            index_store=self.index_store,
            top_k=top_k if top_k is not None else self.settings.retrieval_top_k,
        )
