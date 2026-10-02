"""Contract upload and retrieval endpoints."""

from datetime import date
from typing import Annotated
from uuid import UUID

from app.api.dependencies import DatabaseSession
from app.db.models import ObligationPriority, RiskLevel
from app.db.repositories import (
    ClauseRepository,
    ContractRepository,
    ObligationRepository,
    RiskRepository,
)
from app.schemas.analysis import ContractSummaryResponse
from app.schemas.clause import ClauseRead
from app.schemas.contract import ContractDetail, ContractRead
from app.schemas.obligation import ObligationRead
from app.schemas.risk import RiskRead
from app.services.contract_service import ingest_contract
from app.services.document_service import (
    InvalidPDFError,
    UploadTooLargeError,
    read_upload_safely,
)
from app.services.summary_service import (
    ContractNotFoundError as SummaryContractNotFoundError,
)
from app.services.summary_service import (
    build_contract_summary,
)
from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.post("", response_model=ContractDetail, status_code=status.HTTP_201_CREATED)
async def upload_contract(
    request: Request,
    session: DatabaseSession,
    file: Annotated[UploadFile, File(description="Contract PDF")],
    title: Annotated[str | None, Form(max_length=255)] = None,
) -> ContractDetail:
    max_size = request.app.state.settings.max_pdf_size_bytes
    try:
        data = await read_upload_safely(file, max_size_bytes=max_size)
    except UploadTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(error),
        ) from error

    try:
        contract = ingest_contract(
            session,
            filename=file.filename,
            content_type=file.content_type,
            data=data,
            title=title,
        )
        session.commit()
        stored = ContractRepository(session).get_with_details(contract.id)
        if stored is None:  # pragma: no cover - defensive database guard
            raise RuntimeError("Created contract could not be loaded")
        return ContractDetail.model_validate(stored)
    except InvalidPDFError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.get("", response_model=list[ContractRead])
def list_contracts(
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    contract_type: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    expiration_date_from: Annotated[date | None, Query()] = None,
    expiration_date_to: Annotated[date | None, Query()] = None,
    renewal_date_from: Annotated[date | None, Query()] = None,
    renewal_date_to: Annotated[date | None, Query()] = None,
    party: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
) -> list[ContractRead]:
    _validate_date_range("expiration date", expiration_date_from, expiration_date_to)
    _validate_date_range("renewal date", renewal_date_from, renewal_date_to)
    normalized_type = _normalize_filter("contract_type", contract_type)
    normalized_party = _normalize_filter("party", party)
    return [
        ContractRead.model_validate(contract)
        for contract in ContractRepository(session).list(
            offset=offset,
            limit=limit,
            contract_type=normalized_type,
            expiration_date_from=expiration_date_from,
            expiration_date_to=expiration_date_to,
            renewal_date_from=renewal_date_from,
            renewal_date_to=renewal_date_to,
            party=normalized_party,
        )
    ]


@router.get("/{contract_id}/obligations", response_model=list[ObligationRead])
def list_obligations(
    contract_id: UUID,
    session: DatabaseSession,
    priority: Annotated[ObligationPriority | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ObligationRead]:
    _require_contract(session, contract_id)
    return [
        ObligationRead.model_validate(item)
        for item in ObligationRepository(session).list_for_contract(
            contract_id, priority=priority, offset=offset, limit=limit
        )
    ]


@router.get("/{contract_id}/risks", response_model=list[RiskRead])
def list_risks(
    contract_id: UUID,
    session: DatabaseSession,
    severity: Annotated[RiskLevel | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RiskRead]:
    _require_contract(session, contract_id)
    return [
        RiskRead.model_validate(item)
        for item in RiskRepository(session).list_for_contract(
            contract_id, severity=severity, offset=offset, limit=limit
        )
    ]


@router.get("/{contract_id}/clauses", response_model=list[ClauseRead])
def list_clauses(
    contract_id: UUID,
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ClauseRead]:
    _require_contract(session, contract_id)
    return [
        ClauseRead.model_validate(item)
        for item in ClauseRepository(session).list_for_contract(
            contract_id, offset=offset, limit=limit
        )
    ]


@router.get("/{contract_id}/summary", response_model=ContractSummaryResponse)
def get_contract_summary(
    contract_id: UUID, session: DatabaseSession
) -> ContractSummaryResponse:
    try:
        return build_contract_summary(session, contract_id=contract_id)
    except SummaryContractNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        ) from error


@router.get("/{contract_id}", response_model=ContractDetail)
def get_contract(contract_id: UUID, session: DatabaseSession) -> ContractDetail:
    contract = ContractRepository(session).get_with_details(contract_id)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        )
    return ContractDetail.model_validate(contract)


def _require_contract(session: DatabaseSession, contract_id: UUID) -> None:
    if ContractRepository(session).get(contract_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        )


def _validate_date_range(label: str, start: date | None, end: date | None) -> None:
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{label} start must not be after end",
        )


def _normalize_filter(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{name} cannot be blank",
        )
    return normalized
