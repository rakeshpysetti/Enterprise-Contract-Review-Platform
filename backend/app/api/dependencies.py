"""Shared API dependencies."""

from typing import Annotated

from fastapi import Depends
from fastapi import Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.ai.rag.retriever import ContractRetriever
from app.services.llm_service import LLMService, OllamaLLMService

DatabaseSession = Annotated[Session, Depends(get_db)]


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
