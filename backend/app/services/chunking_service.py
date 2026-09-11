"""Text cleanup used before extracted pages are persisted as chunks."""

import re

_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\r\n]+")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines = [_HORIZONTAL_WHITESPACE.sub(" ", line).strip() for line in normalized.split("\n")]
    return _EXCESS_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
