"""Check real PostgreSQL lock protection and recovery in an isolated test record."""

from datetime import timedelta

from app.db.database import get_engine, get_session_factory
from app.db.models import Contract, ContractStatus, utc_now
from app.services.analysis_service import (
    AnalysisInProgressError,
    recover_contract_analysis,
)
from sqlalchemy import delete, update


def main() -> None:
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise RuntimeError("This check requires PostgreSQL")
    factory = get_session_factory(engine)
    with factory() as session:
        contract = Contract(
            title="Recovery integration check",
            filename="synthetic.pdf",
            tenant_id="integration-lock-check",
            status=ContractStatus.processing,
            updated_at=utc_now() - timedelta(hours=2),
        )
        session.add(contract)
        session.commit()
        identifier = contract.id
    try:
        with factory() as worker, factory() as recovery:
            worker.execute(
                update(Contract)
                .where(Contract.id == identifier)
                .values(
                    title="Active worker lock",
                    updated_at=utc_now() - timedelta(hours=2),
                )
            )
            try:
                recover_contract_analysis(
                    recovery, contract_id=identifier, recovery_seconds=3600
                )
            except AnalysisInProgressError:
                pass
            else:
                raise AssertionError("Recovery bypassed an active worker's row lock")
            worker.rollback()  # Simulates the transaction released by a dead process.
            recovered = recover_contract_analysis(
                recovery,
                contract_id=identifier,
                recovery_seconds=3600,
            )
            assert recovered.status == ContractStatus.failed
        print("PostgreSQL active-lock protection and abandoned-attempt recovery passed")
    finally:
        with factory() as cleanup:
            cleanup.execute(delete(Contract).where(Contract.id == identifier))
            cleanup.commit()


if __name__ == "__main__":
    main()
