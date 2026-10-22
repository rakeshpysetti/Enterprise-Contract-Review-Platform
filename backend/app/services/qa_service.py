"""Contract-specific retrieval-augmented question answering."""

import uuid

from app.ai.chains.qa_chain import ContractQAChain
from app.ai.rag.retriever import ContractRetriever
from app.schemas.analysis import (
    ContractAnswerSource,
    ContractQuestionResponse,
)
from app.services.llm_service import LLMMalformedResponseError, LLMService
from sqlalchemy.orm import Session


class InvalidAnswerCitationError(ValueError):
    pass


def answer_contract_question(
    session: Session,
    *,
    contract_id: uuid.UUID,
    question: str,
    llm: LLMService,
    retriever: ContractRetriever,
    top_k: int | None = None,
) -> ContractQuestionResponse:
    matches = retriever.retrieve(
        session,
        contract_id,
        question,
        top_k=top_k,
    )
    chain = ContractQAChain(llm)
    matches_by_id = {match.chunk.id: match for match in matches}
    for attempt in range(2):
        try:
            generated = chain.run(question, matches)
        except LLMMalformedResponseError:
            if attempt == 0:
                continue
            raise
        invalid_ids = [
            chunk_id
            for chunk_id in generated.cited_chunk_ids
            if chunk_id not in matches_by_id
        ]
        if not invalid_ids:
            break
        if attempt == 1:
            raise InvalidAnswerCitationError(
                "The generated answer cited context that was not retrieved"
            )

    sources = [
        ContractAnswerSource(
            chunk_id=chunk_id,
            excerpt=matches_by_id[chunk_id].chunk.content,
            page_number=matches_by_id[chunk_id].chunk.page_number,
        )
        for chunk_id in generated.cited_chunk_ids
    ]
    return ContractQuestionResponse(
        contract_id=contract_id,
        question=question,
        answered=generated.answer is not None,
        answer=generated.answer,
        sources=sources,
        confidence=generated.confidence,
    )
