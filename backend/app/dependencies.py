"""Dependency injection utilities for the backend application."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from .config import Settings
from .logging.csv_logger import CSVLogger
from .pipeline.dialog import DialogOrchestrator
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
            "ThresholdBreached",
            "SessionId",
            "DialogStatus",
            "MissingParameters",
            "Prompt",
            "Transcript",
        ),
    )


@lru_cache
def get_dialog_orchestrator() -> DialogOrchestrator:
    """Provide a dialog orchestrator wired to the shared pipeline."""

    settings = get_settings()
    pipeline = get_pipeline()
    return DialogOrchestrator(pipeline=pipeline, settings=settings)


__all__ = [
    "get_settings",
    "settings_dependency",
    "get_pipeline",
    "get_csv_logger",
    "get_dialog_orchestrator",
]
