from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.contract import ContractDetail


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
