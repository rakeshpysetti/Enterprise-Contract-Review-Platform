"""Repository classes for database access."""

import uuid
from collections.abc import Sequence
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Clause, Contract, ContractChunk, Obligation, Risk

ModelT = TypeVar("ModelT", Contract, ContractChunk, Obligation, Clause, Risk)


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
                selectinload(Contract.clauses),
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

    def get_many_for_contract(
        self, contract_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, ContractChunk]:
        if not chunk_ids:
            return {}
        statement = select(ContractChunk).where(
            ContractChunk.contract_id == contract_id,
            ContractChunk.id.in_(chunk_ids),
        )
        return {chunk.id: chunk for chunk in self.session.scalars(statement)}


class ObligationRepository(Repository[Obligation]):
    model = Obligation

    def list_for_contract(self, contract_id: uuid.UUID) -> list[Obligation]:
        statement = (
            select(Obligation)
            .where(Obligation.contract_id == contract_id)
            .order_by(Obligation.page_number, Obligation.created_at, Obligation.id)
        )
        return list(self.session.scalars(statement))

    def replace_for_contract(
        self, contract_id: uuid.UUID, obligations: Sequence[Obligation]
    ) -> list[Obligation]:
        for existing in self.list_for_contract(contract_id):
            self.session.delete(existing)
        self.session.flush()
        self.session.add_all(obligations)
        self.session.flush()
        return list(obligations)


class RiskRepository(Repository[Risk]):
    model = Risk

    def list_for_contract(self, contract_id: uuid.UUID) -> list[Risk]:
        statement = (
            select(Risk)
            .where(Risk.contract_id == contract_id)
            .order_by(Risk.page_number, Risk.created_at, Risk.id)
        )
        return list(self.session.scalars(statement))

    def replace_for_contract(
        self, contract_id: uuid.UUID, risks: Sequence[Risk]
    ) -> list[Risk]:
        for existing in self.list_for_contract(contract_id):
            self.session.delete(existing)
        self.session.flush()
        self.session.add_all(risks)
        self.session.flush()
        return list(risks)


class ClauseRepository(Repository[Clause]):
    model = Clause

    def list_for_contract(self, contract_id: uuid.UUID) -> list[Clause]:
        statement = (
            select(Clause)
            .where(Clause.contract_id == contract_id)
            .order_by(Clause.page_number, Clause.created_at, Clause.id)
        )
        return list(self.session.scalars(statement))

    def replace_for_contract(
        self, contract_id: uuid.UUID, clauses: Sequence[Clause]
    ) -> list[Clause]:
        for existing in self.list_for_contract(contract_id):
            self.session.delete(existing)
        self.session.flush()
        self.session.add_all(clauses)
        self.session.flush()
        return list(clauses)
