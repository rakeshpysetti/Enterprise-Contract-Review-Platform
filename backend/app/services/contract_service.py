"""Contract ingestion orchestration."""

from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Contract, ContractChunk, ContractStatus
from app.db.repositories import ContractRepository
from app.services.document_service import InvalidPDFError, validate_pdf
from app.services.extraction_service import extract_pdf_pages


def ingest_contract(
    session: Session,
    *,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    title: str | None = None,
) -> Contract:
    safe_filename = validate_pdf(
        filename=filename, content_type=content_type, data=data
    )
    pages = extract_pdf_pages(data)
    extracted_pages = [page for page in pages if page.text]
    if not extracted_pages:
        raise InvalidPDFError("The PDF does not contain extractable text")

    contract_title = (title or Path(safe_filename).stem).strip()
    if not contract_title:
        raise InvalidPDFError("A contract title is required")

    contract = Contract(
        title=contract_title[:255],
        filename=safe_filename,
        status=ContractStatus.pending,
        chunks=[
            ContractChunk(
                chunk_index=page.page_number - 1,
                page_number=page.page_number,
                content=page.text,
            )
            for page in extracted_pages
        ],
    )
    ContractRepository(session).add(contract)
    return contract
