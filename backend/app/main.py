"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routes.analysis import router as analysis_router
from app.api.routes.health import router as health_router
from app.api.routes.qa import router as qa_router
from app.api.routes.search import router as search_router
from app.api.routes.contracts import router as contracts_router
from app.core.config import Settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(application: FastAPI):
    yield
    llm_service = getattr(application.state, "llm_service", None)
    close = getattr(llm_service, "close", None)
    if callable(close):
        close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    configure_logging()
    application = FastAPI(
        title=settings.app_name, version="0.1.0", lifespan=lifespan
    )
    application.state.settings = settings
    install_exception_handlers(application)
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
