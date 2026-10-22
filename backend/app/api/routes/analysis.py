"""Complete contract analysis endpoint."""

from uuid import UUID

from app.api.dependencies import (
    ContractRetrieverDependency,
    DatabaseSession,
    LLMServiceDependency,
)
from app.core.logging import get_logger
from app.schemas.analysis import ContractAnalysisResponse
from app.schemas.contract import ContractDetail
from app.services.analysis_service import (
    AnalysisExecutionError,
    AnalysisInProgressError,
    ContractNotFoundError,
    recover_contract_analysis,
    run_contract_analysis,
)
from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix="/contracts", tags=["analysis"])


@router.post("/{contract_id}/recover", response_model=ContractDetail)
def recover_analysis(
    contract_id: UUID,
    request: Request,
    session: DatabaseSession,
) -> ContractDetail:
    try:
        contract = recover_contract_analysis(
            session,
            contract_id=contract_id,
            recovery_seconds=request.app.state.settings.analysis_recovery_seconds,
        )
    except ContractNotFoundError as error:
        raise HTTPException(404, "Contract not found") from error
    except AnalysisInProgressError as error:
        raise HTTPException(409, str(error)) from error
    return ContractDetail.model_validate(contract)


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
        cause = error.__cause__
        get_logger().error(
            "analysis_failed",
            extra={
                "contract_id": str(contract_id),
                "error_type": type(cause).__name__ if cause else type(error).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Contract analysis failed",
        ) from error

    return ContractAnalysisResponse(
        **ContractDetail.model_validate(contract).model_dump(),
        analysis_reused=reused,
    )
