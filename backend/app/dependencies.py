"""Dependency injection utilities for the backend application."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from .config import Settings
from .integrations.stt import DeepgramSpeechToTextClient, SpeechToTextClient
from .logging.csv_logger import CSVLogger


CSV_LOG_FIELDS: tuple[str, ...] = (
    "Timestamp",
    "Input",
    "Language",
    "Method",
    "STT",
    "ProcessingTime",
    "LanguageMs",
    "ExtractionMs",
    "NormalizationMs",
    "ValidationMs",
    "Output",
    "Status",
    "ThresholdBreached",
    "MissingFields",
    "InvalidFields",
    "RecognizedAirports",
    "RecognizedDestinations",
    "RecognizedDates",
    "RecognizedDuration",
    "RecognizedFlexibility",
    "SessionId",
    "DialogStatus",
    "MissingParameters",
    "Prompt",
    "Transcript",
)
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
        fieldnames=CSV_LOG_FIELDS,
        delimiter=settings.csv_delimiter,
    )


@lru_cache
def get_dialog_orchestrator() -> DialogOrchestrator:
    """Provide a dialog orchestrator wired to the shared pipeline."""

    settings = get_settings()
    pipeline = get_pipeline()
    return DialogOrchestrator(pipeline=pipeline, settings=settings)


@lru_cache
def get_stt_client() -> SpeechToTextClient | None:
    """Instantiate an STT client when voice capture is enabled."""

    settings = get_settings()
    engine = (settings.stt_engine or "").strip().lower()
    if not settings.voice_enabled or not engine:
        return None

    if engine == "deepgram":
        if not settings.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY must be configured when using the Deepgram STT engine")
        return DeepgramSpeechToTextClient(api_key=settings.deepgram_api_key)

    raise RuntimeError(f"Unsupported STT engine '{settings.stt_engine}' configured")


__all__ = [
    "CSV_LOG_FIELDS",
    "get_settings",
    "settings_dependency",
    "get_pipeline",
    "get_csv_logger",
    "get_dialog_orchestrator",
    "get_stt_client",
]
