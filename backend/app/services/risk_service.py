"""Extract, validate, and persist potential contract risks."""

import re
import uuid

from sqlalchemy.orm import Session

from app.ai.chains.risk_chain import RiskExtractionChain
from app.db.models import Risk
from app.db.repositories import ContractRepository, RiskRepository
from app.schemas.risk import RiskExtraction
from app.services.llm_service import LLMService

_WHITESPACE = re.compile(r"\s+")


class ContractNotFoundError(LookupError):
    pass


class InvalidRiskSourceError(ValueError):
    pass


def extract_and_store_risks(
    session: Session,
    *,
    contract_id: uuid.UUID,
    llm: LLMService,
) -> list[Risk]:
    contract = ContractRepository(session).get_with_details(contract_id)
    if contract is None:
        raise ContractNotFoundError(f"Contract {contract_id} was not found")

    extraction = RiskExtractionChain(llm).run(contract.chunks)
    text_by_page: dict[int, list[str]] = {}
    for chunk in contract.chunks:
        if chunk.page_number is not None:
            text_by_page.setdefault(chunk.page_number, []).append(chunk.content)
    _validate_sources(extraction, text_by_page)

    risks = [
        Risk(
            contract_id=contract.id,
            category=item.category,
            description=item.description,
            level=item.level,
            why_it_matters=item.why_it_matters,
            recommendation=item.recommendation,
            source_text=item.source_text,
            page_number=item.page_number,
            confidence=item.confidence,
        )
        for item in extraction.risks
    ]
    return RiskRepository(session).replace_for_contract(contract.id, risks)


def _validate_sources(
    extraction: RiskExtraction,
    text_by_page: dict[int, list[str]],
) -> None:
    for item in extraction.risks:
        page_text = text_by_page.get(item.page_number)
        if page_text is None:
            raise InvalidRiskSourceError(
                f"Risk references unknown page {item.page_number}"
            )
        source = _normalize(item.source_text)
        page = _normalize(" ".join(page_text))
        if source not in page:
            raise InvalidRiskSourceError(
                f"Risk source text was not found on page {item.page_number}"
            )


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()
