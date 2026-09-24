"""Contract-level analysis orchestration."""

import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ai.chains.extraction_chain import ContractExtractionChain
from app.ai.rag.retriever import ContractRetriever
from app.db.models import Contract, ContractStatus, utc_now
from app.db.repositories import ContractRepository
from app.schemas.contract import ContractMetadata
from app.services.clause_service import detect_and_store_clauses
from app.services.llm_service import LLMService
from app.services.obligation_service import extract_and_store_obligations
from app.services.risk_service import extract_and_store_risks


class ContractNotFoundError(LookupError):
    pass


class AnalysisInProgressError(RuntimeError):
    pass


class AnalysisExecutionError(RuntimeError):
    pass


def extract_and_store_contract_metadata(
    session: Session,
    *,
    contract_id: uuid.UUID,
    llm: LLMService,
) -> ContractMetadata:
    contract = ContractRepository(session).get_with_details(contract_id)
    if contract is None:
        raise ContractNotFoundError(f"Contract {contract_id} was not found")

    metadata = ContractExtractionChain(llm).run(contract.chunks)
    if metadata.title is not None:
        contract.title = metadata.title
    contract.contract_type = metadata.contract_type
    contract.parties = [party.model_dump(mode="json") for party in metadata.parties]
    contract.effective_date = metadata.effective_date
    contract.expiration_date = metadata.expiration_date
    contract.renewal_date = metadata.renewal_date
    contract.governing_law = metadata.governing_law
    contract.payment_terms = metadata.payment_terms
    session.flush()
    return metadata


def run_contract_analysis(
    session: Session,
    *,
    contract_id: uuid.UUID,
    llm: LLMService,
    retriever: ContractRetriever,
) -> tuple[Contract, bool]:
    contract = ContractRepository(session).get(contract_id)
    if contract is None:
        raise ContractNotFoundError(f"Contract {contract_id} was not found")
    if contract.status is ContractStatus.completed:
        completed = ContractRepository(session).get_with_details(contract_id)
        if completed is None:  # pragma: no cover - guarded by the prior lookup
            raise ContractNotFoundError(f"Contract {contract_id} was not found")
        return completed, True
    if contract.status is ContractStatus.processing:
        raise AnalysisInProgressError("Contract analysis is already in progress")

    claimed = session.execute(
        update(Contract)
        .where(
            Contract.id == contract_id,
            Contract.status.in_([ContractStatus.pending, ContractStatus.failed]),
        )
        .values(status=ContractStatus.processing, updated_at=utc_now())
    ).rowcount
    if claimed != 1:
        session.rollback()
        current = ContractRepository(session).get(contract_id)
        if current is None:
            raise ContractNotFoundError(f"Contract {contract_id} was not found")
        if current.status is ContractStatus.completed:
            completed = ContractRepository(session).get_with_details(contract_id)
            if completed is None:  # pragma: no cover - defensive race guard
                raise ContractNotFoundError(f"Contract {contract_id} was not found")
            return completed, True
        raise AnalysisInProgressError("Contract analysis is already in progress")
    session.commit()

    try:
        retriever.ensure_index(session, contract_id)
        extract_and_store_contract_metadata(session, contract_id=contract_id, llm=llm)
        extract_and_store_obligations(session, contract_id=contract_id, llm=llm)
        detect_and_store_clauses(session, contract_id=contract_id, llm=llm)
        extract_and_store_risks(session, contract_id=contract_id, llm=llm)
        analyzed = ContractRepository(session).get(contract_id)
        if analyzed is None:  # pragma: no cover - contract cannot disappear normally
            raise ContractNotFoundError(f"Contract {contract_id} was not found")
        analyzed.status = ContractStatus.completed
        session.commit()
    except Exception as error:
        session.rollback()
        failed = ContractRepository(session).get(contract_id)
        if failed is not None:
            failed.status = ContractStatus.failed
            session.commit()
        raise AnalysisExecutionError("Contract analysis failed") from error

    session.expire_all()
    result = ContractRepository(session).get_with_details(contract_id)
    if result is None:  # pragma: no cover - guarded by successful commit
        raise ContractNotFoundError(f"Contract {contract_id} was not found")
    return result, False
