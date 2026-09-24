"""Complete contract analysis endpoint."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import (
    ContractRetrieverDependency,
    DatabaseSession,
    LLMServiceDependency,
)
from app.schemas.analysis import ContractAnalysisResponse
from app.schemas.contract import ContractDetail
from app.services.analysis_service import (
    AnalysisExecutionError,
    AnalysisInProgressError,
    ContractNotFoundError,
    run_contract_analysis,
)

router = APIRouter(prefix="/contracts", tags=["analysis"])


@router.post("/{contract_id}/analyze", response_model=ContractAnalysisResponse)
def analyze_contract(
    contract_id: UUID,
    session: DatabaseSession,
    llm: LLMServiceDependency,
    retriever: ContractRetrieverDependency,
) -> ContractAnalysisResponse:
    try:
        contract, reused = run_contract_analysis(
            session,
            contract_id=contract_id,
            llm=llm,
            retriever=retriever,
        )
    except ContractNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        ) from error
    except AnalysisInProgressError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    except AnalysisExecutionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Contract analysis failed",
        ) from error

    return ContractAnalysisResponse(
        **ContractDetail.model_validate(contract).model_dump(),
        analysis_reused=reused,
    )
