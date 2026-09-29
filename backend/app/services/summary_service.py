"""Build a concise summary from persisted contract analysis results."""

import uuid

from sqlalchemy.orm import Session

from app.db.models import RiskLevel
from app.db.repositories import ContractRepository
from app.schemas.analysis import (
    ContractImportantDates,
    ContractRiskCounts,
    ContractSummaryClause,
    ContractSummaryResponse,
)

_RISK_ORDER = {
    RiskLevel.low: 0,
    RiskLevel.medium: 1,
    RiskLevel.high: 2,
    RiskLevel.critical: 3,
}


class ContractNotFoundError(LookupError):
    pass


def build_contract_summary(
    session: Session, *, contract_id: uuid.UUID
) -> ContractSummaryResponse:
    contract = ContractRepository(session).get_with_details(contract_id)
    if contract is None:
        raise ContractNotFoundError(f"Contract {contract_id} was not found")

    counts = {level: 0 for level in RiskLevel}
    for risk in contract.risks:
        counts[risk.level] += 1
    overall = (
        max(
            (level for level, count in counts.items() if count > 0),
            key=_RISK_ORDER.__getitem__,
        )
        if any(counts.values())
        else None
    )
    clauses = sorted(
        contract.clauses,
        key=lambda item: (item.page_number, item.created_at, item.id),
    )

    return ContractSummaryResponse(
        contract_id=contract.id,
        title=contract.title,
        contract_type=contract.contract_type,
        status=contract.status,
        risk_counts=ContractRiskCounts(
            low=counts[RiskLevel.low],
            medium=counts[RiskLevel.medium],
            high=counts[RiskLevel.high],
            critical=counts[RiskLevel.critical],
            total=sum(counts.values()),
        ),
        obligation_count=len(contract.obligations),
        important_dates=ContractImportantDates(
            effective_date=contract.effective_date,
            expiration_date=contract.expiration_date,
            renewal_date=contract.renewal_date,
        ),
        key_clauses=[
            ContractSummaryClause(
                clause_type=clause.clause_type,
                source_excerpt=clause.source_text,
                page_number=clause.page_number,
                confidence=clause.confidence,
            )
            for clause in clauses
        ],
        overall_risk_level=overall,
    )
