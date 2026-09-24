from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
