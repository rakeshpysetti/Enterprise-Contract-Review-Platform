"""Contract upload and retrieval endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status

from app.api.dependencies import DatabaseSession
from app.db.repositories import ContractRepository
from app.schemas.contract import ContractDetail, ContractRead
from app.services.contract_service import ingest_contract
from app.services.document_service import InvalidPDFError

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
        data = await file.read(max_size + 1)
    finally:
        await file.close()
    if len(data) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"PDF exceeds the {max_size}-byte upload limit",
        )

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
) -> list[ContractRead]:
    return [
        ContractRead.model_validate(contract)
        for contract in ContractRepository(session).list(offset=offset, limit=limit)
    ]


@router.get("/{contract_id}", response_model=ContractDetail)
def get_contract(contract_id: UUID, session: DatabaseSession) -> ContractDetail:
    contract = ContractRepository(session).get_with_details(contract_id)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        )
    return ContractDetail.model_validate(contract)
