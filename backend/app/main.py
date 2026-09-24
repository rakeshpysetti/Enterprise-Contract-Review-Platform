"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.analysis import router as analysis_router
from app.api.routes.health import router as health_router
from app.api.routes.search import router as search_router
from app.api.routes.contracts import router as contracts_router
from app.core.config import Settings


@asynccontextmanager
async def lifespan(application: FastAPI):
    yield
    llm_service = getattr(application.state, "llm_service", None)
    close = getattr(llm_service, "close", None)
    if callable(close):
        close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    application = FastAPI(
        title=settings.app_name, version="0.1.0", lifespan=lifespan
    )
    application.state.settings = settings
    application.include_router(health_router)
    application.include_router(contracts_router)
    application.include_router(analysis_router)
    application.include_router(search_router)
    return application


app = create_app()
