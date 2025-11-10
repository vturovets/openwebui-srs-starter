"""Dependency injection utilities for the backend application."""

from __future__ import annotations

from functools import lru_cache
from typing import AsyncIterator, Iterable, Iterator

from .config import Settings
from .pipeline.configuration import MethodsCatalog

from .integrations.stt import (
    DeepgramSpeechToTextClient,
    FasterWhisperSpeechToTextClient,
    SpeechToTextClient,
    SpeechToTextError,
    TranscriptionResult,
)
from .integrations.llm import LLMClientRegistry
from .logging.csv_logger import CSVLogger


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
        llm_registry=get_llm_client(),
        methods_catalog=get_methods_catalog(),
    )


@lru_cache
def get_llm_client() -> LLMClientRegistry | None:
    """Instantiate LLM clients for configured methods when credentials are present."""

    settings = get_settings()
    catalog = get_methods_catalog()

    registry = LLMClientRegistry.from_methods_catalog(
        settings=settings,
        catalog=catalog,
        fixtures_dir=settings.fixtures_dir,
    )
    return registry if len(registry) > 0 else None


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

    if engine in {"whisper", "faster-whisper"}:

        class _LazyFasterWhisperClient:
            """Defer Whisper model loading until the first transcription call."""

            def __init__(self) -> None:
                self._client: FasterWhisperSpeechToTextClient | None = None

            async def transcribe(
                self,
                *,
                content_type: str,
                stream: AsyncIterator[bytes] | Iterable[bytes],
            ) -> TranscriptionResult:
                if self._client is None:
                    try:
                        self._client = FasterWhisperSpeechToTextClient(
                            model_size=settings.whisper_model_size,
                            device=settings.whisper_device,
                            compute_type=settings.whisper_compute_type,
                            download_root=settings.whisper_download_root,
                            beam_size=settings.whisper_beam_size,
                            vad_filter=settings.whisper_vad_filter,
                        )
                    except SpeechToTextError:
                        # Surface provider errors through the endpoint handler.
                        raise

                return await self._client.transcribe(
                    content_type=content_type,
                    stream=stream,
                )

        return _LazyFasterWhisperClient()

    raise RuntimeError(f"Unsupported STT engine '{settings.stt_engine}' configured")


__all__ = [
    "CSV_LOG_FIELDS",
    "get_settings",
    "settings_dependency",
    "get_methods_catalog",
    "get_pipeline",
    "get_llm_client",
    "get_csv_logger",
    "get_dialog_orchestrator",
    "get_stt_client",
]
