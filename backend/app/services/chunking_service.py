"""Text cleanup used before extracted pages are persisted as chunks."""

import re

from llama_index.core.node_parser import SentenceSplitter

_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\r\n]+")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_SPLITTER = SentenceSplitter(chunk_size=192, chunk_overlap=24)


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines = [
        _HORIZONTAL_WHITESPACE.sub(" ", line).strip() for line in normalized.split("\n")
    ]
    return _EXCESS_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def split_page_text(text: str) -> list[str]:
    """Split pages into bounded, overlapping retrieval chunks with LlamaIndex."""
    if not text:
        return []
    return [chunk for chunk in _SPLITTER.split_text(text) if chunk.strip()]
