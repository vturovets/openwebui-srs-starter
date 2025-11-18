"""Dependency injection utilities for the backend application."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from functools import lru_cache
from typing import Callable, Iterator, Mapping

from .config import Settings
from .pipeline.configuration import MethodsCatalog
from .services.auto_completion import AutoCompletionService
from .integrations.stt import (
    DeepgramSpeechToTextClient,
    FasterWhisperSpeechToTextClient,
    SpeechToTextClient,
)
from .integrations.llm import HolidaySearchLLMClient
from .logging import (
    CSVLogger,
    ImportSummaryLogger,
    IMPORT_SUMMARY_LOG_FIELDS,
)


# NOTE: "Language Detection" is intentionally duplicated. The first column captures the
# language detection timing (`languageMs`), while the second records the semantic
# detection result (code plus confidence).
CSV_LOG_FIELDS: tuple[str, ...] = (
    "Timestamp (UTC)",
    "User input",
    "Request type",
    "Method",
    "Interaction Mode",
    "Pipeline Status",
    "Language Detection",
    "Processing Time",
    "Language Detection",
    "Extraction",
    "Mapping",
    "Validation",
    "Transcription",
    "Network Latency",
    "Output",
)
from .pipeline.dialog import DialogOrchestrator
from .pipeline.pipeline import HolidaySearchPipeline

logger = logging.getLogger(__name__)


@lru_cache
def get_settings() -> Settings:
    """Return the shared application settings instance."""

    settings = Settings()
    settings.ensure_directories()
    settings.load_methods_catalog()
    return settings


def settings_dependency() -> Iterator[Settings]:
    """Provide settings for FastAPI dependency injection."""

    yield get_settings()


@lru_cache
def get_methods_catalog() -> MethodsCatalog:
    """Provide a cached view of the configured method catalogue."""

    settings = get_settings()
    return settings.load_methods_catalog()


@lru_cache
def get_pipeline() -> HolidaySearchPipeline:
    """Return a shared pipeline instance configured from application settings."""

    settings = get_settings()
    return HolidaySearchPipeline(
        settings=settings,
        fixtures_dir=settings.fixtures_dir,
        llm_client=get_llm_client(),
        methods_catalog=get_methods_catalog(),
    )


@lru_cache
def get_auto_completion_service() -> AutoCompletionService:
    """Instantiate the auto-completion service with shared resources."""

    settings = get_settings()
    pipeline = get_pipeline()
    stats_path = settings.resolve_popularity_data_path()
    stats_payload = _load_popularity_stats(str(stats_path))
    return AutoCompletionService(
        fixtures=pipeline.fixtures,
        configuration=pipeline.configuration,
        stats_payload=stats_payload,
        stats_path=stats_path,
    )


@lru_cache
def get_llm_client() -> Callable[[str], Mapping[str, object]] | None:
    """Instantiate the configured LLM client when credentials are provided."""

    settings = get_settings()
    if not (settings.llm_api_key and settings.llm_api_key.strip()):
        return None

    client = HolidaySearchLLMClient(settings=settings, fixtures_dir=settings.fixtures_dir)
    return client


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
def get_import_summary_logger() -> ImportSummaryLogger | None:
    """Provide a CSV logger that stores one row per import job."""

    settings = get_settings()
    if settings.import_summary_path is None:
        return None

    return ImportSummaryLogger(
        path=settings.import_summary_path,
        fieldnames=IMPORT_SUMMARY_LOG_FIELDS,
        delimiter=settings.import_summary_delimiter,
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
        api_key = (settings.deepgram_api_key or "").strip()
        if api_key:
            return DeepgramSpeechToTextClient(api_key=api_key)

        try:
            return FasterWhisperSpeechToTextClient(
                model=settings.fallback_whisper_model,
                device=settings.fallback_whisper_device,
                compute_type=settings.fallback_whisper_compute_type,
                cache_dir=settings.fallback_whisper_cache_dir,
                voice_max_bytes=settings.voice_max_bytes,
            )
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            raise RuntimeError(
                "Deepgram credentials are missing and the faster-whisper fallback could not be initialised",
            ) from exc

    raise RuntimeError(f"Unsupported STT engine '{settings.stt_engine}' configured")


__all__ = [
    "CSV_LOG_FIELDS",
    "get_settings",
    "settings_dependency",
    "get_methods_catalog",
    "get_pipeline",
    "get_auto_completion_service",
    "get_llm_client",
    "get_csv_logger",
    "get_import_summary_logger",
    "get_dialog_orchestrator",
    "get_stt_client",
    "IMPORT_SUMMARY_LOG_FIELDS",
]


@lru_cache
def _load_popularity_stats(path: str) -> Mapping[str, object] | None:
    stats_path = Path(path)
    if not stats_path.is_file():
        logger.warning("Popularity statistics file '%s' not found", stats_path)
        return None
    try:
        text = stats_path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem dependent
        logger.warning("Unable to read popularity statistics '%s': %s", stats_path, exc)
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - depends on fixture integrity
        logger.warning("Invalid JSON in popularity statistics '%s': %s", stats_path, exc)
        return None
