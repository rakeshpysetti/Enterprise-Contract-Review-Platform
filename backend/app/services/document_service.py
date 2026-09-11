"""Validation helpers for uploaded contract documents."""

from pathlib import Path

import fitz

PDF_MEDIA_TYPES = {"application/pdf", "application/x-pdf"}


class InvalidPDFError(ValueError):
    pass


def validate_pdf(*, filename: str | None, content_type: str | None, data: bytes) -> str:
    safe_filename = Path(filename.replace("\\", "/")).name if filename else ""
    if not safe_filename or Path(safe_filename).suffix.lower() != ".pdf":
        raise InvalidPDFError("A filename ending in .pdf is required")
    media_type = content_type.partition(";")[0].strip().lower() if content_type else None
    if media_type and media_type not in PDF_MEDIA_TYPES:
        raise InvalidPDFError("The uploaded file must use the application/pdf media type")
    if not data:
        raise InvalidPDFError("The uploaded PDF is empty")
    if not data.startswith(b"%PDF-"):
        raise InvalidPDFError("The uploaded file does not have a PDF signature")

    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise InvalidPDFError("Password-protected PDFs are not supported")
            if document.page_count == 0:
                raise InvalidPDFError("The PDF does not contain any pages")
    except InvalidPDFError:
        raise
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise InvalidPDFError("The uploaded PDF is damaged or invalid") from error

    return safe_filename
