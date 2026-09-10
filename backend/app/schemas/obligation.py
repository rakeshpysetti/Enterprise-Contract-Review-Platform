from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ObligationCreate(BaseModel):
    contract_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    responsible_party: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    source_text: str | None = None


class ObligationRead(ObligationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
