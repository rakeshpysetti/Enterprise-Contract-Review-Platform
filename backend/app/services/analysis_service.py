"""Contract-level analysis orchestration."""

import uuid
from datetime import timedelta

from app.ai.chains.extraction_chain import ContractExtractionChain
from app.ai.rag.retriever import ContractRetriever
from app.db.models import Contract, ContractStatus, utc_now
from app.db.repositories import ContractRepository
from app.schemas.contract import ContractMetadata
from app.services.clause_service import detect_and_store_clauses
from app.services.llm_service import LLMService
from app.services.obligation_service import extract_and_store_obligations
from app.services.risk_service import extract_and_store_risks
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


class ContractNotFoundError(LookupError):
    pass


class AnalysisInProgressError(RuntimeError):
    pass


class AnalysisExecutionError(RuntimeError):
    pass


def recover_contract_analysis(
    session: Session,
    *,
    contract_id: uuid.UUID,
    recovery_seconds: int,
) -> Contract:
    """Release only an abandoned attempt; active PostgreSQL workers hold a row lock."""
    if ContractRepository(session).get(contract_id) is None:
        raise ContractNotFoundError("Contract not found")
    try:
        session.execute(
            select(Contract.id)
            .where(Contract.id == contract_id)
            .with_for_update(nowait=True)
        )
        recovered = session.execute(
            update(Contract)
            .where(
                Contract.id == contract_id,
                Contract.status == ContractStatus.processing,
                Contract.updated_at < utc_now() - timedelta(seconds=recovery_seconds),
            )
            .values(
                status=ContractStatus.failed,
                analysis_attempt_id=None,
                updated_at=utc_now(),
            )
        ).rowcount
    except OperationalError as error:
        session.rollback()
        raise AnalysisInProgressError(
            "Analysis is still active; try again later"
        ) from error
    if recovered != 1:
        session.rollback()
        raise AnalysisInProgressError("Only stale processing attempts can be recovered")
    session.commit()
    session.expire_all()
    contract = ContractRepository(session).get_with_details(contract_id)
    if contract is None:
        raise ContractNotFoundError("Contract not found")
    return contract


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

    attempt_id = uuid.uuid4()
    claimed = session.execute(
        update(Contract)
        .where(
            Contract.id == contract_id,
            Contract.status.in_([ContractStatus.pending, ContractStatus.failed]),
        )
        .values(
            status=ContractStatus.processing,
            updated_at=utc_now(),
            analysis_attempt_id=attempt_id,
        )
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
        # Fence the attempt and retain the write lock until results are committed.
        # A terminated process releases this transaction while leaving the durable
        # processing claim available for explicit recovery after the timeout.
        locked = session.execute(
            update(Contract)
            .where(
                Contract.id == contract_id,
                Contract.status == ContractStatus.processing,
                Contract.analysis_attempt_id == attempt_id,
            )
            .values(updated_at=utc_now())
        ).rowcount
        if locked != 1:
            raise AnalysisInProgressError("Analysis attempt has been superseded")
        retriever.ensure_index(session, contract_id)
        extract_and_store_contract_metadata(session, contract_id=contract_id, llm=llm)
        extract_and_store_obligations(session, contract_id=contract_id, llm=llm)
        detect_and_store_clauses(session, contract_id=contract_id, llm=llm)
        extract_and_store_risks(session, contract_id=contract_id, llm=llm)
        analyzed = ContractRepository(session).get(contract_id)
        if analyzed is None:  # pragma: no cover - contract cannot disappear normally
            raise ContractNotFoundError(f"Contract {contract_id} was not found")
        analyzed.status = ContractStatus.completed
        analyzed.analysis_attempt_id = None
        session.commit()
    except Exception as error:
        session.rollback()
        session.execute(
            update(Contract)
            .where(
                Contract.id == contract_id,
                Contract.analysis_attempt_id == attempt_id,
                Contract.status == ContractStatus.processing,
            )
            .values(
                status=ContractStatus.failed,
                analysis_attempt_id=None,
                updated_at=utc_now(),
            )
        )
        session.commit()
        raise AnalysisExecutionError("Contract analysis failed") from error

    session.expire_all()
    result = ContractRepository(session).get_with_details(contract_id)
    if result is None:  # pragma: no cover - guarded by successful commit
        raise ContractNotFoundError(f"Contract {contract_id} was not found")
    return result, False
