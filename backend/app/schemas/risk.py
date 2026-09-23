from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import RiskLevel


class ExtractedRisk(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    level: RiskLevel
    why_it_matters: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class RiskExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risks: list[ExtractedRisk] = Field(default_factory=list)


class RiskCreate(ExtractedRisk):
    contract_id: UUID


class RiskRead(RiskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
