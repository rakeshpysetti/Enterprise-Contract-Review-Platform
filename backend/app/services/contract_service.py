"""Contract ingestion orchestration."""

from pathlib import Path

from app.db.models import Contract, ContractChunk, ContractStatus
from app.db.repositories import ContractRepository
from app.services.chunking_service import split_page_text
from app.services.document_service import InvalidPDFError, validate_pdf
from app.services.extraction_service import extract_pdf_pages
from sqlalchemy.orm import Session


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

    page_chunks = [
        (page.page_number, chunk)
        for page in extracted_pages
        for chunk in split_page_text(page.text)
    ]
    contract = Contract(
        tenant_id=session.info.get("tenant_id", "legacy"),
        title=contract_title[:255],
        filename=safe_filename,
        status=ContractStatus.pending,
        chunks=[
            ContractChunk(
                chunk_index=index,
                page_number=page_number,
                content=chunk,
            )
            for index, (page_number, chunk) in enumerate(page_chunks)
        ],
    )
    ContractRepository(session).add(contract)
    return contract
