from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ContractStatus
from app.schemas.obligation import ObligationRead
from app.schemas.risk import RiskRead


class ContractParty(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=255)


class ContractMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    contract_type: str | None = Field(default=None, min_length=1, max_length=255)
    parties: list[ContractParty] = Field(default_factory=list)
    effective_date: date | None = None
    expiration_date: date | None = None
    renewal_date: date | None = None
    governing_law: str | None = Field(default=None, min_length=1, max_length=255)
    payment_terms: str | None = Field(default=None, min_length=1)


class ContractBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    effective_date: date | None = None
    expiration_date: date | None = None
    renewal_date: date | None = None
    contract_type: str | None = None
    parties: list[ContractParty] = Field(default_factory=list)
    governing_law: str | None = None
    payment_terms: str | None = None


class ContractCreate(ContractBase):
    pass


class ContractUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: ContractStatus | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    renewal_date: date | None = None
    contract_type: str | None = Field(default=None, min_length=1, max_length=255)
    parties: list[ContractParty] | None = None
    governing_law: str | None = Field(default=None, min_length=1, max_length=255)
    payment_terms: str | None = Field(default=None, min_length=1)


class ContractRead(ContractBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: ContractStatus
    created_at: datetime
    updated_at: datetime


class ContractChunkCreate(BaseModel):
    contract_id: UUID
    chunk_index: int = Field(ge=0)
    content: str
    page_number: int | None = Field(default=None, ge=1)


class ContractChunkRead(ContractChunkCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class ContractDetail(ContractRead):
    chunks: list[ContractChunkRead]
    obligations: list[ObligationRead]
    risks: list[RiskRead]
