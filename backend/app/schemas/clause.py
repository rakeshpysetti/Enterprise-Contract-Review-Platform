"""Structured clause detection schemas."""

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClauseType(str, enum.Enum):
    termination = "termination"
    renewal = "renewal"
    payment = "payment"
    confidentiality = "confidentiality"
    indemnification = "indemnification"
    limitation_of_liability = "limitation_of_liability"
    sla = "sla"
    data_protection = "data_protection"
    dispute_resolution = "dispute_resolution"


class DetectedClause(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    clause_type: ClauseType
    source_text: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class ClauseDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clauses: list[DetectedClause] = Field(default_factory=list)


class ClauseRead(DetectedClause):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    created_at: datetime
