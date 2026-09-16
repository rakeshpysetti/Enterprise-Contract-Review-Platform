"""Shared API dependencies."""

from typing import Annotated

from fastapi import Depends
from fastapi import Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.ai.rag.retriever import ContractRetriever

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
