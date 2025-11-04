"""Dependency injection utilities for the backend application."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from .config import Settings
from .logging.csv_logger import CSVLogger
from .pipeline.pipeline import HolidaySearchPipeline


@lru_cache
def get_settings() -> Settings:
    """Return the shared application settings instance."""

    settings = Settings()
    settings.ensure_directories()
    return settings


def settings_dependency() -> Iterator[Settings]:
    """Provide settings for FastAPI dependency injection."""

    yield get_settings()


@lru_cache
def get_pipeline() -> HolidaySearchPipeline:
    """Return a shared pipeline instance configured from application settings."""

    settings = get_settings()
    return HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)


@lru_cache
def get_csv_logger() -> CSVLogger:
    """Provide a shared CSV logger configured from application settings."""

    settings = get_settings()
    return CSVLogger(
        path=settings.csv_path,
        fieldnames=(
            "Timestamp",
            "Input",
            "Language",
            "Method",
            "STT",
            "ProcessingTime",
            "Output",
            "Status",
        ),
    )


__all__ = ["get_settings", "settings_dependency", "get_pipeline", "get_csv_logger"]
