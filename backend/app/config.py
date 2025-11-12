"""Application configuration management.

This module centralizes runtime configuration using Pydantic settings so that
values can be sourced from ``.env`` files while providing sensible defaults for
the MVP described in the SRS.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_core import PydanticUndefined

from .pipeline.configuration import MethodsCatalog, load_methods_catalog


class Settings(BaseSettings):
    """Settings loaded from environment variables or ``.env`` files."""

    interaction_mode: str = Field(
        default="direct-parse",
        alias="INTERACTION_MODE",
        description=(
            "Configurable interaction mode: either 'direct-parse' to process "
            "requests without clarification or 'dialog' to enable follow-up "
            "questions."
        ),
    )
    allowed_langs: List[str] = Field(
        default_factory=lambda: ["en"],
        alias="ALLOWED_LANGS",
        description="List of ISO language codes supported by the NLP pipeline.",
    )
    csv_path: Path = Field(
        default=Path("data/log.csv"),
        alias="CSV_PATH",
        description="Filesystem path for the CSV log that captures conversions.",
    )
    csv_delimiter: str = Field(
        default=",",
        alias="CSV_DELIMITER",
        description="Single-character delimiter used for the CSV audit log.",
    )
    import_summary_path: Path | None = Field(
        default=Path("data/import_summary.csv"),
        alias="IMPORT_SUMMARY_PATH",
        description=(
            "Filesystem path for aggregated import job summaries. Set to an empty string to disable logging."
        ),
    )
    import_summary_delimiter: str = Field(
        default=",",
        alias="IMPORT_SUMMARY_DELIMITER",
        description="Single-character delimiter used for the import summary CSV sink.",
    )
    llm_method: Optional[str] = Field(
        default=None,
        alias="LLM_METHOD",
        description="Identifier for the primary LLM/NLP method in use.",
    )
    llm_api_base: Optional[str] = Field(
        default=None,
        alias="LLM_API_BASE",
        description="Base URL for the structured extraction LLM provider.",
    )
    llm_api_key: Optional[str] = Field(
        default=None,
        alias="LLM_API_KEY",
        description="API token for authenticating with the configured LLM provider.",
    )
    llm_model: str = Field(
        default="gpt-3.5-turbo",
        alias="LLM_MODEL",
        description="Model identifier to request from the LLM provider.",
    )
    llm_timeout: float = Field(
        default=30.0,
        alias="LLM_TIMEOUT",
        description="Timeout (seconds) for outbound LLM requests.",
    )
    stt_engine: Optional[str] = Field(
        default=None,
        alias="STT_ENGINE",
        description="Speech-to-text engine identifier used for voice capture.",
    )
    deepgram_api_key: Optional[str] = Field(
        default=None,
        alias="DEEPGRAM_API_KEY",
        description="API token used when STT_ENGINE is configured to 'deepgram'.",
    )
    voice_enabled: bool = Field(
        default=False,
        alias="VOICE_ENABLED",
        description="Toggle voice capture support for the UI and pipelines.",
    )
    show_failed_only: bool = Field(
        default=True,
        alias="SHOW_FAILED_ONLY",
        description=(
            "When importing request logs, limit the UI to displaying only entries "
            "that did not succeed."
        ),
    )
    import_worker_concurrency: int = Field(
        default=8,
        alias="IMPORT_WORKER_CONCURRENCY",
        description=(
            "Maximum number of concurrent tasks when running bulk import jobs."
        ),
    )
    import_max_concurrency: int = Field(
        default=32,
        alias="IMPORT_MAX_CONCURRENCY",
        description=(
            "Hard ceiling applied to import concurrency regardless of overrides."
        ),
    )
    import_batch_size: int = Field(
        default=64,
        alias="IMPORT_BATCH_SIZE",
        description=(
            "Number of requests scheduled before awaiting running import tasks."
        ),
    )
    import_cpu_threshold: Optional[float] = Field(
        default=90.0,
        alias="IMPORT_CPU_THRESHOLD",
        description=(
            "Pause import scheduling when estimated CPU utilisation exceeds this percentage."
        ),
    )
    import_memory_threshold_mb: Optional[int] = Field(
        default=4096,
        alias="IMPORT_MEMORY_THRESHOLD_MB",
        description=(
            "Pause import scheduling when estimated RAM usage exceeds this many megabytes."
        ),
    )
    import_pause_seconds: float = Field(
        default=0.1,
        alias="IMPORT_PAUSE_SECONDS",
        description=(
            "Sleep interval applied while waiting for system resources to recover during import throttling."
        ),
    )
    import_p95_threshold_ms: int = Field(
        default=1000,
        alias="IMPORT_P95_THRESHOLD_MS",
        description=(
            "Maximum acceptable P95 response time, in milliseconds, for imported "
            "log performance summaries."
        ),
    )
    import_p95_sample_size: int = Field(
        default=1000,
        alias="IMPORT_P95_SAMPLE_SIZE",
        description=(
            "Minimum number of import records required before calculating the P95 "
            "response time."
        ),
    )
    import_p95_significance: float = Field(
        default=0.95,
        alias="IMPORT_P95_SIGNIFICANCE",
        description=(
            "Significance level expressed as a percentile (0-1) when evaluating "
            "imported performance data."
        ),
    )
    voice_max_bytes: int = Field(
        default=10_000_000,
        alias="VOICE_MAX_BYTES",
        description="Maximum audio payload size accepted by the voice endpoint (bytes).",
    )
    voice_allowed_content_types: List[str] = Field(
        default_factory=lambda: [
            "audio/wav",
            "audio/x-wav",
            "audio/mpeg",
            "audio/mp3",
            "audio/ogg",
            "audio/webm",
            "video/webm",
            "audio/flac",
        ],
        alias="VOICE_ALLOWED_CONTENT_TYPES",
        description="List of MIME types accepted for audio uploads.",
    )
    fixtures_dir: Path = Field(
        default=Path("fixtures"),
        alias="FIXTURES_DIR",
        description="Directory containing validation fixture data.",
    )
    methods_config_path: Path = Field(
        default=Path("config/methods.yaml"),
        alias="METHODS_CONFIG_PATH",
        description="Filesystem path to the methods catalogue YAML file.",
    )
    processing_threshold_ms: int = Field(
        default=1000,
        alias="PROCESSING_THRESHOLD_MS",
        description="Target maximum processing time in milliseconds.",
    )
    methods_catalog: MethodsCatalog | None = Field(default=None, exclude=True)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        populate_by_name=True,
        arbitrary_types_allowed=True,
        # Allow validators to handle comma-separated ``.env`` overrides (e.g.
        # VOICE_ALLOWED_CONTENT_TYPES) without triggering JSON decode errors for
        # blank values by skipping automatic decoding in the settings sources.
        enable_decoding=False,
    )

    @field_validator("allowed_langs", mode="before")
    @classmethod
    def _split_allowed_langs(cls, value: object) -> List[str]:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value is None:
            return ["en"]
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned or ["en"]
        raise TypeError("ALLOWED_LANGS must be provided as a comma-separated string or list")

    @field_validator("voice_allowed_content_types", mode="before")
    @classmethod
    def _split_allowed_content_types(cls, value: object) -> List[str]:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value is None:
            return [
                "audio/wav",
                "audio/x-wav",
                "audio/mpeg",
                "audio/mp3",
                "audio/ogg",
                "audio/webm",
                "video/webm",
                "audio/flac",
            ]
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned or [
                "audio/wav",
                "audio/x-wav",
                "audio/mpeg",
                "audio/mp3",
                "audio/ogg",
                "audio/webm",
                "video/webm",
                "audio/flac",
            ]
        raise TypeError(
            "VOICE_ALLOWED_CONTENT_TYPES must be provided as a comma-separated string or list",
        )

    @field_validator("import_worker_concurrency", mode="before")
    @classmethod
    def _validate_import_worker_concurrency(cls, value: object) -> int:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 8
        try:
            concurrency = int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_WORKER_CONCURRENCY must be a positive integer") from exc
        if concurrency < 1:
            raise ValueError("IMPORT_WORKER_CONCURRENCY must be at least 1")
        return concurrency

    @field_validator("import_max_concurrency", mode="before")
    @classmethod
    def _validate_import_max_concurrency(cls, value: object) -> int:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 32
        try:
            ceiling = int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_MAX_CONCURRENCY must be a positive integer") from exc
        if ceiling < 1:
            raise ValueError("IMPORT_MAX_CONCURRENCY must be at least 1")
        return ceiling

    @field_validator("import_batch_size", mode="before")
    @classmethod
    def _validate_import_batch_size(cls, value: object) -> int:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 64
        try:
            batch_size = int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_BATCH_SIZE must be a positive integer") from exc
        if batch_size < 1:
            raise ValueError("IMPORT_BATCH_SIZE must be at least 1")
        return batch_size

    @field_validator("import_cpu_threshold", mode="before")
    @classmethod
    def _validate_import_cpu_threshold(cls, value: object) -> Optional[float]:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 90.0
        try:
            threshold = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_CPU_THRESHOLD must be a numeric value") from exc
        if threshold <= 0 or threshold > 100:
            raise ValueError("IMPORT_CPU_THRESHOLD must be greater than 0 and at most 100")
        return threshold

    @field_validator("import_memory_threshold_mb", mode="before")
    @classmethod
    def _validate_import_memory_threshold(cls, value: object) -> Optional[int]:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 4096
        try:
            threshold = int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_MEMORY_THRESHOLD_MB must be a positive integer") from exc
        if threshold <= 0:
            raise ValueError("IMPORT_MEMORY_THRESHOLD_MB must be greater than zero")
        return threshold

    @field_validator("import_pause_seconds", mode="before")
    @classmethod
    def _validate_import_pause_seconds(cls, value: object) -> float:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 0.1
        try:
            pause = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_PAUSE_SECONDS must be a numeric value") from exc
        if pause <= 0:
            raise ValueError("IMPORT_PAUSE_SECONDS must be greater than zero seconds")
        return pause

    @field_validator("import_p95_threshold_ms", mode="before")
    @classmethod
    def _validate_import_p95_threshold(cls, value: object) -> int:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 1000
        try:
            threshold = int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_P95_THRESHOLD_MS must be a positive integer") from exc
        if threshold <= 0:
            raise ValueError("IMPORT_P95_THRESHOLD_MS must be greater than zero")
        return threshold

    @field_validator("import_p95_sample_size", mode="before")
    @classmethod
    def _validate_import_p95_sample_size(cls, value: object) -> int:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 1000
        try:
            sample_size = int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_P95_SAMPLE_SIZE must be a positive integer") from exc
        if sample_size <= 0:
            raise ValueError("IMPORT_P95_SAMPLE_SIZE must be greater than zero")
        return sample_size

    @field_validator("import_p95_significance", mode="before")
    @classmethod
    def _validate_import_p95_significance(cls, value: object) -> float:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 0.95
        try:
            significance = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("IMPORT_P95_SIGNIFICANCE must be a numeric value between 0 and 1") from exc
        if not 0 < significance < 1:
            raise ValueError("IMPORT_P95_SIGNIFICANCE must be greater than 0 and less than 1")
        return significance

    @field_validator("csv_delimiter", mode="before")
    @classmethod
    def _validate_csv_delimiter(cls, value: object) -> str:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value is None:
            return ","
        if isinstance(value, str):
            delimiter = value.strip()
            if len(delimiter) != 1:
                raise ValueError("CSV_DELIMITER must be a single visible character")
            return delimiter
        raise TypeError("CSV_DELIMITER must be provided as a single-character string")

    @field_validator("csv_path", "fixtures_dir", "methods_config_path", mode="before")
    @classmethod
    def _ensure_path(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str):
            return Path(value)
        raise TypeError("Expected a filesystem path string for CSV_PATH/FIXTURES_DIR")

    def load_methods_catalog(self) -> MethodsCatalog:
        """Load and cache the configured methods catalogue."""

        if self.methods_catalog is None:
            catalog = load_methods_catalog(self.methods_config_path)
            object.__setattr__(self, "methods_catalog", catalog)
        return self.methods_catalog

    @field_validator("llm_api_base", "llm_api_key", mode="before")
    @classmethod
    def _strip_optional_string(cls, value: object) -> Optional[str]:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        raise TypeError("LLM API configuration values must be provided as strings")

    @field_validator("llm_model", mode="before")
    @classmethod
    def _validate_llm_model(cls, value: object) -> str:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value is None:
            return "gpt-3.5-turbo"
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return "gpt-3.5-turbo"
            return cleaned
        raise TypeError("LLM_MODEL must be provided as a string value")

    @field_validator("llm_timeout", mode="before")
    @classmethod
    def _validate_llm_timeout(cls, value: object) -> float:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return 30.0
        try:
            timeout = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("LLM_TIMEOUT must be a numeric value") from exc
        if timeout <= 0:
            raise ValueError("LLM_TIMEOUT must be greater than zero seconds")
        return timeout

    @field_validator("import_summary_path", mode="before")
    @classmethod
    def _validate_import_summary_path(cls, value: object) -> Path | None:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, "", "null", "None"):
            return None
        if isinstance(value, Path):
            return value
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            return Path(cleaned)
        raise TypeError("IMPORT_SUMMARY_PATH must be a filesystem path or empty to disable logging")

    @field_validator("import_summary_delimiter", mode="before")
    @classmethod
    def _validate_import_summary_delimiter(cls, value: object) -> str:
        if value is PydanticUndefined:
            return value  # type: ignore[return-value]
        if value in (None, ""):
            return ","
        if not isinstance(value, str):
            raise TypeError("IMPORT_SUMMARY_DELIMITER must be a string")
        cleaned = value.strip()
        if len(cleaned) != 1:
            raise ValueError("IMPORT_SUMMARY_DELIMITER must be a single character")
        return cleaned

    def ensure_directories(self) -> None:
        """Create required directories for runtime artifacts if missing."""

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.fixtures_dir.mkdir(parents=True, exist_ok=True)
        if self.import_summary_path is not None:
            self.import_summary_path.parent.mkdir(parents=True, exist_ok=True)


__all__ = ["Settings"]
