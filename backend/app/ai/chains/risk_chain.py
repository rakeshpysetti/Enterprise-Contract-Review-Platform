"""Structured contract risk extraction chain."""

from pathlib import Path

from app.ai.chains.extraction_chain import format_contract_chunks
from app.db.models import ContractChunk
from app.schemas.risk import RiskExtraction
from app.services.llm_service import LLMService

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "risk_analysis.txt"


class RiskExtractionChain:
    def __init__(self, llm: LLMService, *, prompt_path: Path = PROMPT_PATH) -> None:
        self.llm = llm
        self.prompt_template = prompt_path.read_text(encoding="utf-8")
        if "{{CONTRACT_TEXT}}" not in self.prompt_template:
            raise ValueError("Risk analysis prompt is missing its text placeholder")

    def run(self, chunks: list[ContractChunk]) -> RiskExtraction:
        if not chunks:
            raise ValueError("Contract does not contain text chunks")
        prompt = self.prompt_template.replace(
            "{{CONTRACT_TEXT}}", format_contract_chunks(chunks)
        )
        return self.llm.generate_structured(prompt, RiskExtraction)
