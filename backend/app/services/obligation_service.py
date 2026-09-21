"""Extract, validate, and persist contract obligations."""

import re
import uuid

from sqlalchemy.orm import Session

from app.ai.chains.obligation_chain import ObligationExtractionChain
from app.db.models import Obligation
from app.db.repositories import ContractRepository, ObligationRepository
from app.schemas.obligation import ObligationExtraction
from app.services.llm_service import LLMService

_WHITESPACE = re.compile(r"\s+")


class ContractNotFoundError(LookupError):
    pass


class InvalidObligationSourceError(ValueError):
    pass


def extract_and_store_obligations(
    session: Session,
    *,
    contract_id: uuid.UUID,
    llm: LLMService,
) -> list[Obligation]:
    contract = ContractRepository(session).get_with_details(contract_id)
    if contract is None:
        raise ContractNotFoundError(f"Contract {contract_id} was not found")

    extraction = ObligationExtractionChain(llm).run(contract.chunks)
    text_by_page: dict[int, list[str]] = {}
    for chunk in contract.chunks:
        if chunk.page_number is not None:
            text_by_page.setdefault(chunk.page_number, []).append(chunk.content)
    _validate_sources(extraction, text_by_page)

    obligations = [
        Obligation(
            contract_id=contract.id,
            title=item.title,
            description=item.description,
            responsible_party=item.responsible_party,
            counterparty=item.counterparty,
            due_date=item.due_date,
            recurring_frequency=item.recurring_frequency,
            priority=item.priority,
            source_text=item.source_text,
            page_number=item.page_number,
            confidence=item.confidence,
        )
        for item in extraction.obligations
    ]
    return ObligationRepository(session).replace_for_contract(contract.id, obligations)


def _validate_sources(
    extraction: ObligationExtraction,
    text_by_page: dict[int, list[str]],
) -> None:
    for item in extraction.obligations:
        page_text = text_by_page.get(item.page_number)
        if page_text is None:
            raise InvalidObligationSourceError(
                f"Obligation references unknown page {item.page_number}"
            )
        normalized_source = _normalize(item.source_text)
        normalized_page = _normalize(" ".join(page_text))
        if normalized_source not in normalized_page:
            raise InvalidObligationSourceError(
                f"Obligation source text was not found on page {item.page_number}"
            )


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()
