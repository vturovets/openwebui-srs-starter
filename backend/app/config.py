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
    llm_method: Optional[str] = Field(
        default=None,
        alias="LLM_METHOD",
        description="Identifier for the primary LLM/NLP method in use.",
    )
    stt_engine: Optional[str] = Field(
        default=None,
        alias="STT_ENGINE",
        description="Speech-to-text engine identifier used for voice capture.",
    )
    voice_enabled: bool = Field(
        default=False,
        alias="VOICE_ENABLED",
        description="Toggle voice capture support for the UI and pipelines.",
    )
    fixtures_dir: Path = Field(
        default=Path("fixtures"),
        alias="FIXTURES_DIR",
        description="Directory containing validation fixture data.",
    )
    processing_threshold_ms: int = Field(
        default=1000,
        alias="PROCESSING_THRESHOLD_MS",
        description="Target maximum processing time in milliseconds.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
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

    @field_validator("csv_path", "fixtures_dir", mode="before")
    @classmethod
    def _ensure_path(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str):
            return Path(value)
        raise TypeError("Expected a filesystem path string for CSV_PATH/FIXTURES_DIR")

    def ensure_directories(self) -> None:
        """Create required directories for runtime artifacts if missing."""

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.fixtures_dir.mkdir(parents=True, exist_ok=True)


__all__ = ["Settings"]
