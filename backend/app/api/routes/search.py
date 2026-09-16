"""Contract-scoped semantic search endpoint."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.ai.rag.index import VectorIndexError
from app.api.dependencies import ContractRetrieverDependency, DatabaseSession
from app.schemas.analysis import (
    ContractSearchRequest,
    ContractSearchResponse,
    ContractSearchResult,
)
from app.services.retrieval_service import (
    ContractHasNoChunksError,
    ContractNotFoundError,
)

router = APIRouter(prefix="/contracts", tags=["search"])


@router.post("/{contract_id}/search", response_model=ContractSearchResponse)
def search_contract(
    contract_id: UUID,
    request: ContractSearchRequest,
    session: DatabaseSession,
    retriever: ContractRetrieverDependency,
) -> ContractSearchResponse:
    try:
        matches = retriever.retrieve(
            session,
            contract_id,
            request.query,
            top_k=request.top_k,
        )
    except ContractNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        ) from error
    except ContractHasNoChunksError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    except VectorIndexError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Contract search index is unavailable",
        ) from error

    return ContractSearchResponse(
        contract_id=contract_id,
        query=request.query,
        results=[
            ContractSearchResult(
                chunk_id=match.chunk.id,
                text=match.chunk.content,
                page_number=match.chunk.page_number,
                similarity_score=match.score,
            )
            for match in matches
        ],
    )
