"""Structured contract metadata extraction chain."""

from pathlib import Path

from app.db.models import ContractChunk
from app.schemas.contract import ContractMetadata
from app.services.llm_service import LLMService

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "contract_extraction.txt"


class ContractExtractionChain:
    def __init__(self, llm: LLMService, *, prompt_path: Path = PROMPT_PATH) -> None:
        self.llm = llm
        self.prompt_template = prompt_path.read_text(encoding="utf-8")
        if "{{CONTRACT_TEXT}}" not in self.prompt_template:
            raise ValueError("Contract extraction prompt is missing its text placeholder")

    def run(self, chunks: list[ContractChunk]) -> ContractMetadata:
        if not chunks:
            raise ValueError("Contract does not contain text chunks")
        contract_text = format_contract_chunks(chunks)
        prompt = self.prompt_template.replace("{{CONTRACT_TEXT}}", contract_text)
        return self.llm.generate_structured(prompt, ContractMetadata)


def format_contract_chunks(chunks: list[ContractChunk]) -> str:
    return "\n\n".join(
        f"[PAGE {chunk.page_number or 'UNKNOWN'}]\n{chunk.content}"
        for chunk in sorted(chunks, key=lambda item: item.chunk_index)
    )
