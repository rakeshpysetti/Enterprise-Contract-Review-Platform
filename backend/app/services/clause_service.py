"""Detect contract clauses and validate their source evidence."""

import re
import uuid

from sqlalchemy.orm import Session

from app.ai.chains.clause_chain import ClauseDetectionChain
from app.db.models import Clause
from app.db.repositories import ClauseRepository, ContractRepository
from app.schemas.clause import ClauseDetection
from app.services.llm_service import LLMService

_WHITESPACE = re.compile(r"\s+")


class ContractNotFoundError(LookupError):
    pass


class InvalidClauseSourceError(ValueError):
    pass


def detect_and_store_clauses(
    session: Session,
    *,
    contract_id: uuid.UUID,
    llm: LLMService,
) -> list[Clause]:
    contract = ContractRepository(session).get_with_details(contract_id)
    if contract is None:
        raise ContractNotFoundError(f"Contract {contract_id} was not found")

    detection = ClauseDetectionChain(llm).run(contract.chunks)
    text_by_page: dict[int, list[str]] = {}
    for chunk in contract.chunks:
        if chunk.page_number is not None:
            text_by_page.setdefault(chunk.page_number, []).append(chunk.content)
    _validate_sources(detection, text_by_page)
    clauses = [
        Clause(
            contract_id=contract.id,
            clause_type=item.clause_type.value,
            source_text=item.source_text,
            page_number=item.page_number,
            confidence=item.confidence,
        )
        for item in detection.clauses
    ]
    return ClauseRepository(session).replace_for_contract(contract.id, clauses)


def _validate_sources(
    detection: ClauseDetection,
    text_by_page: dict[int, list[str]],
) -> None:
    for clause in detection.clauses:
        page_text = text_by_page.get(clause.page_number)
        if page_text is None:
            raise InvalidClauseSourceError(
                f"Clause references unknown page {clause.page_number}"
            )
        source = _normalize(clause.source_text)
        page = _normalize(" ".join(page_text))
        if source not in page:
            raise InvalidClauseSourceError(
                f"Clause source text was not found on page {clause.page_number}"
            )


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()
