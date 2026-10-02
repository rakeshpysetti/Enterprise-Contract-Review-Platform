"""Request context, safe error fallback, and metadata-only access logs."""

import re
import time
import uuid

from app.api.errors import error_response
from app.core.logging import get_logger
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        generated_id = str(uuid.uuid4())
        request_id = request.headers.get("X-Request-ID", generated_id)
        correlation_id = request.headers.get("X-Correlation-ID", request_id)
        request.state.request_id = generated_id
        request.state.correlation_id = generated_id

        invalid_header = None
        if not _SAFE_ID.fullmatch(request_id):
            invalid_header = "X-Request-ID"
        elif not _SAFE_ID.fullmatch(correlation_id):
            invalid_header = "X-Correlation-ID"
        if invalid_header is not None:
            return error_response(
                request,
                status_code=400,
                code="invalid_request_header",
                message=f"{invalid_header} contains invalid characters or is too long",
            )

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        started = time.perf_counter()
        logger = get_logger()
        try:
            response = await call_next(request)
        except Exception as error:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            logger.error(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "method": request.method,
                    "route": _route_template(request),
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "error_type": type(error).__name__,
                },
            )
            return error_response(
                request,
                status_code=500,
                code="internal_server_error",
                message="An unexpected server error occurred",
            )

        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "correlation_id": correlation_id,
                "method": request.method,
                "route": _route_template(request),
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "<unmatched>"
