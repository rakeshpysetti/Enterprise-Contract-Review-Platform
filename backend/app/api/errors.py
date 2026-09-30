"""Centralized API error responses."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def request_identifiers(request: Request) -> tuple[str, str]:
    request_id = getattr(request.state, "request_id", "unavailable")
    correlation_id = getattr(request.state, "correlation_id", request_id)
    return request_id, correlation_id


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id, correlation_id = request_identifiers(request)
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
        "correlation_id": correlation_id,
    }
    if details is not None:
        error["details"] = details
    response_headers = {
        "X-Request-ID": request_id,
        "X-Correlation-ID": correlation_id,
    }
    if headers:
        response_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        content={"detail": message, "error": error},
        headers=response_headers,
    )


def install_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request, exception: HTTPException
    ) -> JSONResponse:
        message = (
            exception.detail
            if isinstance(exception.detail, str)
            else "The request could not be completed"
        )
        return error_response(
            request,
            status_code=exception.status_code,
            code=f"http_{exception.status_code}",
            message=message,
            headers=exception.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exception.errors()
        ]
        return error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details=details,
        )
