"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.search import router as search_router
from app.api.routes.contracts import router as contracts_router
from app.core.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    application = FastAPI(title=settings.app_name, version="0.1.0")
    application.state.settings = settings
    application.include_router(health_router)
    application.include_router(contracts_router)
    application.include_router(search_router)
    return application


app = create_app()
