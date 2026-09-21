from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ObligationPriority


class ExtractedObligation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    responsible_party: str | None = Field(default=None, max_length=255)
    counterparty: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    recurring_frequency: str | None = Field(default=None, min_length=1, max_length=255)
    priority: ObligationPriority
    source_text: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class ObligationExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obligations: list[ExtractedObligation] = Field(default_factory=list)


class ObligationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    responsible_party: str | None = Field(default=None, max_length=255)
    counterparty: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    recurring_frequency: str | None = Field(default=None, min_length=1, max_length=255)
    priority: ObligationPriority
    source_text: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class ObligationRead(ObligationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
