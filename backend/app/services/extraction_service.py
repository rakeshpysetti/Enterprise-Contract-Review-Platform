"""Page-aware PDF text extraction using PyMuPDF."""

from dataclasses import dataclass

import pymupdf as fitz
from app.services.chunking_service import clean_text
from app.services.document_service import InvalidPDFError


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    text: str


def extract_pdf_pages(
    data: bytes, *, max_total_chars: int = 16000
) -> list[ExtractedPage]:
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise InvalidPDFError("Password-protected PDFs are not supported")
            pages: list[ExtractedPage] = []
            total_chars = 0
            for page in document:
                content = clean_text(page.get_text("text"))
                total_chars += len(content)
                if total_chars > max_total_chars:
                    raise InvalidPDFError(
                        f"Extracted text exceeds the {max_total_chars}-character limit"
                    )
                pages.append(ExtractedPage(page_number=page.number + 1, text=content))
            return pages
    except InvalidPDFError:
        raise
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise InvalidPDFError("Text could not be extracted from the PDF") from error
