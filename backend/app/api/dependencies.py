"""Shared API dependencies."""

from typing import Annotated

from app.ai.rag.retriever import ContractRetriever
from app.api.auth import Principal, current_principal
from app.db.database import get_db
from app.db.models import Contract
from app.services.llm_service import LLMService, OllamaLLMService
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

RawDatabaseSession = Annotated[Session, Depends(get_db)]


def get_tenant_db(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    session: RawDatabaseSession,
) -> Session:
    if (
        request.method == "POST"
        and not request.url.path.endswith(("/search", "/questions"))
        and principal.role != "reviewer"
    ):
        raise HTTPException(403, "Reviewer access is required")
    session.info["tenant_id"] = principal.tenant_id
    contract_id = request.path_params.get("contract_id")
    if contract_id is not None:
        from uuid import UUID

        try:
            identifier = UUID(str(contract_id))
        except ValueError:
            return session  # Let FastAPI return its standard path validation error.
        owned = session.scalar(
            select(Contract.id).where(
                Contract.id == identifier,
                Contract.tenant_id == principal.tenant_id,
            )
        )
        if owned is None:
            raise HTTPException(404, "Contract not found")
    return session


DatabaseSession = Annotated[Session, Depends(get_tenant_db)]


def get_contract_retriever(request: Request) -> ContractRetriever:
    retriever = getattr(request.app.state, "contract_retriever", None)
    if retriever is None:
        retriever = ContractRetriever(request.app.state.settings)
        request.app.state.contract_retriever = retriever
    return retriever


ContractRetrieverDependency = Annotated[
    ContractRetriever, Depends(get_contract_retriever)
]


def get_llm_service(request: Request) -> LLMService:
    service = getattr(request.app.state, "llm_service", None)
    if service is None:
        settings = request.app.state.settings
        service = OllamaLLMService(
            base_url=str(settings.ollama_base_url),
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
            max_retries=settings.ollama_max_retries,
            retry_backoff_seconds=settings.ollama_retry_backoff_seconds,
            temperature=settings.ollama_temperature,
        )
        request.app.state.llm_service = service
    return service


LLMServiceDependency = Annotated[LLMService, Depends(get_llm_service)]
