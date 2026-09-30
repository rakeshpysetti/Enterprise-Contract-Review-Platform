"""Validation helpers for uploaded contract documents."""

from pathlib import Path
from tempfile import SpooledTemporaryFile

import fitz
from fastapi import UploadFile

PDF_MEDIA_TYPES = {"application/pdf", "application/x-pdf"}


class InvalidPDFError(ValueError):
    pass


class UploadTooLargeError(ValueError):
    pass


async def read_upload_safely(
    upload: UploadFile,
    *,
    max_size_bytes: int,
    chunk_size: int = 64 * 1024,
) -> bytes:
    if max_size_bytes <= 0:
        raise ValueError("Upload size limit must be positive")
    spool_limit = min(max_size_bytes, 1024 * 1024)
    total = 0
    try:
        with SpooledTemporaryFile(max_size=spool_limit, mode="w+b") as temporary:
            while chunk := await upload.read(chunk_size):
                total += len(chunk)
                if total > max_size_bytes:
                    raise UploadTooLargeError(
                        f"PDF exceeds the {max_size_bytes}-byte upload limit"
                    )
                temporary.write(chunk)
            temporary.seek(0)
            return temporary.read()
    finally:
        await upload.close()


def validate_pdf(*, filename: str | None, content_type: str | None, data: bytes) -> str:
    safe_filename = Path(filename.replace("\\", "/")).name if filename else ""
    if (
        not safe_filename
        or len(safe_filename) > 255
        or any(ord(character) < 32 for character in safe_filename)
        or Path(safe_filename).suffix.lower() != ".pdf"
    ):
        raise InvalidPDFError("A filename ending in .pdf is required")
    media_type = content_type.partition(";")[0].strip().lower() if content_type else None
    if media_type not in PDF_MEDIA_TYPES:
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
