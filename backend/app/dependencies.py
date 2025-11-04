"""Dependency injection utilities for the backend application."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from .config import Settings


@lru_cache
def get_settings() -> Settings:
    """Return the shared application settings instance."""

    settings = Settings()
    settings.ensure_directories()
    return settings


def settings_dependency() -> Iterator[Settings]:
    """Provide settings for FastAPI dependency injection."""

    yield get_settings()


__all__ = ["get_settings", "settings_dependency"]
