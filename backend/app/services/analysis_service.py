"""Contract-level analysis orchestration."""

import uuid

from sqlalchemy.orm import Session

from app.ai.chains.extraction_chain import ContractExtractionChain
from app.db.repositories import ContractRepository
from app.schemas.contract import ContractMetadata
from app.services.llm_service import LLMService


class ContractNotFoundError(LookupError):
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
