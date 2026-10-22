"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Annotated

from app.api.auth import Principal, current_principal
from app.api.errors import install_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.request_limits import RequestBodyLimitMiddleware
from app.api.routes.analysis import router as analysis_router
from app.api.routes.contracts import router as contracts_router
from app.api.routes.health import router as health_router
from app.api.routes.qa import router as qa_router
from app.api.routes.search import router as search_router
from app.core.config import Settings
from app.core.logging import configure_logging
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    yield
    llm_service = getattr(application.state, "llm_service", None)
    close = getattr(llm_service, "close", None)
    if callable(close):
        close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    configure_logging()
    application = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    application.state.settings = settings
    application.state.model_capacity = BoundedSemaphore(
        settings.max_concurrent_model_requests
    )
    application.state.llm_initialization_lock = Lock()
    web_directory = Path(__file__).parent / "web"
    application.mount("/assets", StaticFiles(directory=web_directory), name="assets")

    @application.get("/", include_in_schema=False)
    def review_interface() -> FileResponse:
        return FileResponse(
            web_directory / "index.html",
            headers={
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; img-src 'self' data:; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.get("/auth/me", response_model=Principal, tags=["access"])
    def identity(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        return principal

    @application.get("/system/info", tags=["access"])
    def system_info(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> dict[str, str]:
        return {
            "version": application.version,
            "ollama_model": settings.ollama_model,
            "embedding_model": settings.embedding_model,
        }

    install_exception_handlers(application)
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_pdf_size_bytes=settings.max_pdf_size_bytes,
        max_request_body_bytes=settings.max_request_body_bytes,
    )
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Correlation-ID",
                "X-Request-ID",
            ],
            expose_headers=["X-Correlation-ID", "X-Request-ID"],
        )
    application.add_middleware(RequestContextMiddleware)
    application.include_router(health_router)
    application.include_router(contracts_router)
    application.include_router(analysis_router)
    application.include_router(search_router)
    application.include_router(qa_router)
    return application


app = create_app()
