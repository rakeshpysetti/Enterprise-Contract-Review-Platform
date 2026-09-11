"""Page-aware PDF text extraction using PyMuPDF."""

from dataclasses import dataclass

import fitz

from app.services.chunking_service import clean_text
from app.services.document_service import InvalidPDFError


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    text: str


def extract_pdf_pages(data: bytes) -> list[ExtractedPage]:
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise InvalidPDFError("Password-protected PDFs are not supported")
            return [
                ExtractedPage(
                    page_number=page.number + 1,
                    text=clean_text(page.get_text("text")),
                )
                for page in document
            ]
    except InvalidPDFError:
        raise
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise InvalidPDFError("Text could not be extracted from the PDF") from error
