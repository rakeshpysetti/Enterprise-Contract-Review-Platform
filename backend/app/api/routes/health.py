"""Liveness and dependency-readiness endpoints."""

from typing import Literal

import httpx
from app.api.dependencies import DatabaseSession
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    services: dict[str, Literal["ok", "unavailable"]]


def database_is_ready(session: Session) -> bool:
    try:
        return session.scalar(text("SELECT 1")) == 1
    except SQLAlchemyError:
        return False


def ollama_is_ready(base_url: str, timeout_seconds: float) -> bool:
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/api/tags",
            timeout=min(timeout_seconds, 5.0),
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness(
    request: Request, session: DatabaseSession
) -> ReadinessResponse | JSONResponse:
    settings = request.app.state.settings
    services: dict[str, Literal["ok", "unavailable"]] = {
        "database": "ok" if database_is_ready(session) else "unavailable",
        "ollama": (
            "ok"
            if ollama_is_ready(
                str(settings.ollama_base_url), settings.ollama_timeout_seconds
            )
            else "unavailable"
        ),
    }
    ready = all(service == "ok" for service in services.values())
    payload = ReadinessResponse(
        status="ok" if ready else "unavailable",
        services=services,
    )
    if not ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(),
        )
    return payload
