from datetime import date
from uuid import UUID

from app.db.models import ContractStatus, RiskLevel
from app.schemas.clause import ClauseType
from app.schemas.contract import ContractDetail
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=100)


class ContractSearchResult(BaseModel):
    chunk_id: UUID
    text: str
    page_number: int | None
    similarity_score: float = Field(ge=-1, le=1)


class ContractSearchResponse(BaseModel):
    contract_id: UUID
    query: str
    results: list[ContractSearchResult]


class ContractAnalysisResponse(ContractDetail):
    analysis_reused: bool


class ContractQuestionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=100)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    answer: str | None = Field(default=None, min_length=1)
    cited_chunk_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_answer_citations(self) -> "GroundedAnswer":
        if self.answer is None:
            if self.cited_chunk_ids or self.confidence != 0:
                raise ValueError(
                    "An unanswered question cannot include citations or confidence"
                )
        elif not self.cited_chunk_ids:
            raise ValueError("A grounded answer requires at least one citation")
        if len(self.cited_chunk_ids) != len(set(self.cited_chunk_ids)):
            raise ValueError("Cited chunk identifiers must be unique")
        return self


class ContractAnswerSource(BaseModel):
    chunk_id: UUID
    excerpt: str
    page_number: int | None


class ContractQuestionResponse(BaseModel):
    contract_id: UUID
    question: str
    answered: bool
    answer: str | None
    sources: list[ContractAnswerSource]
    confidence: float = Field(ge=0, le=1)


class ContractRiskCounts(BaseModel):
    low: int = Field(ge=0)
    medium: int = Field(ge=0)
    high: int = Field(ge=0)
    critical: int = Field(ge=0)
    total: int = Field(ge=0)


class ContractImportantDates(BaseModel):
    effective_date: date | None
    expiration_date: date | None
    renewal_date: date | None


class ContractSummaryClause(BaseModel):
    clause_type: ClauseType
    source_excerpt: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class ContractSummaryResponse(BaseModel):
    contract_id: UUID
    title: str
    contract_type: str | None
    status: ContractStatus
    risk_counts: ContractRiskCounts
    obligation_count: int = Field(ge=0)
    important_dates: ContractImportantDates
    key_clauses: list[ContractSummaryClause]
    overall_risk_level: RiskLevel | None
