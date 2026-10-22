"""Bound request bodies before multipart or JSON parsing consumes them."""

from app.api.errors import error_response
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    def __init__(
        self, app: ASGIApp, *, max_pdf_size_bytes: int, max_request_body_bytes: int
    ) -> None:
        self.app = app
        self.max_pdf_size_bytes = max_pdf_size_bytes
        self.max_request_body_bytes = max_request_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.max_request_body_bytes
        if scope["method"] == "POST" and scope["path"].rstrip("/") == "/contracts":
            limit += self.max_pdf_size_bytes  # Allow bounded multipart overhead.
        declared = [
            value
            for name, value in scope["headers"]
            if name.lower() == b"content-length"
        ]
        try:
            if len(declared) > 1:
                raise ValueError("Multiple content lengths")
            length = int(declared[0]) if declared else None
            if length is not None and length < 0:
                raise ValueError("Negative content length")
        except ValueError:
            response = error_response(
                Request(scope),
                status_code=400,
                code="invalid_content_length",
                message="Content-Length must be a single nonnegative integer",
            )
            await response(scope, receive, send)
            return
        if length is not None and length > limit:
            response = error_response(
                Request(scope),
                status_code=413,
                code="request_body_too_large",
                message="Request body exceeds the configured size limit",
            )
            await response(scope, receive, send)
            return

        consumed = 0

        async def bounded_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise HTTPException(
                        413, "Request body exceeds the configured size limit"
                    )
            return message

        await self.app(scope, bounded_receive, send)
