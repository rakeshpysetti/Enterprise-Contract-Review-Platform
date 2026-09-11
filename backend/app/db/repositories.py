"""Repository classes for database access."""

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Contract, ContractChunk, Obligation, Risk

ModelT = TypeVar("ModelT", Contract, ContractChunk, Obligation, Risk)


class Repository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, offset: int = 0, limit: int = 100) -> list[ModelT]:
        statement = select(self.model).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()


class ContractRepository(Repository[Contract]):
    model = Contract

    def get_with_details(self, contract_id: uuid.UUID) -> Contract | None:
        statement = (
            select(Contract)
            .where(Contract.id == contract_id)
            .options(
                selectinload(Contract.chunks),
                selectinload(Contract.obligations),
                selectinload(Contract.risks),
            )
        )
        return self.session.scalar(statement)

    def list(self, *, offset: int = 0, limit: int = 100) -> list[Contract]:
        statement = (
            select(Contract)
            .order_by(Contract.created_at.desc(), Contract.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))


class ContractChunkRepository(Repository[ContractChunk]):
    model = ContractChunk

    def list_for_contract(self, contract_id: uuid.UUID) -> list[ContractChunk]:
        statement = (
            select(ContractChunk)
            .where(ContractChunk.contract_id == contract_id)
            .order_by(ContractChunk.chunk_index)
        )
        return list(self.session.scalars(statement))


class ObligationRepository(Repository[Obligation]):
    model = Obligation

    def list_for_contract(self, contract_id: uuid.UUID) -> list[Obligation]:
        statement = select(Obligation).where(Obligation.contract_id == contract_id)
        return list(self.session.scalars(statement))


class RiskRepository(Repository[Risk]):
    model = Risk

    def list_for_contract(self, contract_id: uuid.UUID) -> list[Risk]:
        statement = select(Risk).where(Risk.contract_id == contract_id)
        return list(self.session.scalars(statement))
