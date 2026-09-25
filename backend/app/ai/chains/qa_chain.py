"""Grounded contract question-answering chain."""

from pathlib import Path

from app.schemas.analysis import GroundedAnswer
from app.services.llm_service import LLMService
from app.services.retrieval_service import RetrievalResult

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "qa.txt"


class ContractQAChain:
    def __init__(self, llm: LLMService, *, prompt_path: Path = PROMPT_PATH) -> None:
        self.llm = llm
        self.prompt_template = prompt_path.read_text(encoding="utf-8")
        required = ("{{QUESTION}}", "{{CONTEXT}}")
        if any(placeholder not in self.prompt_template for placeholder in required):
            raise ValueError("Q&A prompt is missing a required placeholder")

    def run(
        self, question: str, matches: list[RetrievalResult]
    ) -> GroundedAnswer:
        if not question.strip():
            raise ValueError("A question is required")
        context = "\n\n".join(
            (
                f"[CHUNK {match.chunk.id}] [PAGE "
                f"{match.chunk.page_number or 'UNKNOWN'}]\n{match.chunk.content}"
            )
            for match in matches
        )
        prefix, question_separator, remainder = self.prompt_template.partition(
            "{{QUESTION}}"
        )
        middle, context_separator, suffix = remainder.partition("{{CONTEXT}}")
        if not question_separator or not context_separator:
            raise ValueError("Q&A prompt is missing a required placeholder")
        prompt = prefix + question + middle + context + suffix
        return self.llm.generate_structured(prompt, GroundedAnswer)
