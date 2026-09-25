"""Contract-specific question-answering endpoint."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.ai.rag.index import VectorIndexError
from app.api.dependencies import (
    ContractRetrieverDependency,
    DatabaseSession,
    LLMServiceDependency,
)
from app.schemas.analysis import ContractQuestionRequest, ContractQuestionResponse
from app.services.llm_service import LLMServiceError
from app.services.qa_service import InvalidAnswerCitationError, answer_contract_question
from app.services.retrieval_service import (
    ContractHasNoChunksError,
    ContractNotFoundError,
)

router = APIRouter(prefix="/contracts", tags=["questions"])


@router.post("/{contract_id}/questions", response_model=ContractQuestionResponse)
def ask_contract_question(
    contract_id: UUID,
    request: ContractQuestionRequest,
    session: DatabaseSession,
    retriever: ContractRetrieverDependency,
    llm: LLMServiceDependency,
) -> ContractQuestionResponse:
    try:
        return answer_contract_question(
            session,
            contract_id=contract_id,
            question=request.question,
            llm=llm,
            retriever=retriever,
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
    except (LLMServiceError, InvalidAnswerCitationError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="A grounded contract answer could not be generated",
        ) from error
