from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ContractStatus


class ContractBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    effective_date: date | None = None
    expiration_date: date | None = None


class ContractCreate(ContractBase):
    pass


class ContractUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: ContractStatus | None = None
    effective_date: date | None = None
    expiration_date: date | None = None


class ContractRead(ContractBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: ContractStatus
    created_at: datetime
    updated_at: datetime


class ContractChunkCreate(BaseModel):
    contract_id: UUID
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)


class ContractChunkRead(ContractChunkCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
