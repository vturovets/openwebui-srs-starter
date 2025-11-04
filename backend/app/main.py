"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from .api import api_router
from .config import Settings
from .dependencies import get_pipeline, get_settings


def create_app() -> FastAPI:
    """Instantiate and configure the FastAPI application."""

    app = FastAPI(title="OpenWebUI SRS Starter Backend", version="0.1.0")

    @app.on_event("startup")
    async def load_configuration() -> None:
        settings = get_settings()
        app.state.settings = settings

    @app.on_event("shutdown")
    async def clear_configuration_cache() -> None:
        # FastAPI lifespan should eventually replace this when we have more
        # resources to manage, but for now this keeps caches fresh across reloads.
        get_settings.cache_clear()  # type: ignore[attr-defined]
        get_pipeline.cache_clear()  # type: ignore[attr-defined]

    @app.get("/health", tags=["health"])
    async def healthcheck(settings: Settings = Depends(get_settings)) -> dict[str, str]:
        return {
            "status": "ok",
            "interaction_mode": settings.interaction_mode,
        }

    app.include_router(api_router)

    return app


app = create_app()

__all__ = ["app", "create_app"]
