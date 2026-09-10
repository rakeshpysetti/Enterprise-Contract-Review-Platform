from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import RiskLevel


class RiskCreate(BaseModel):
    contract_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    level: RiskLevel
    score: float | None = Field(default=None, ge=0, le=1)
    recommendation: str | None = None
    source_text: str | None = None


class RiskRead(RiskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
