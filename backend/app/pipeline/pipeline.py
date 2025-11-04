"""Pipeline orchestration and configuration helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from ..config import Settings
from ..fixtures.repository import FixtureRepository
from .configuration import SearchConfiguration
from .extractor_rules import RulesExtractor
from .language import LanguageDetector
from .normalizer import Normalizer
from .validator import Validator

class HolidaySearchPipeline:
    """Co-ordinate language detection, extraction, normalisation, and validation."""

    CONFIG_FILENAME = "configuration_search.json"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        fixtures_dir: str | Path | None = None,
    ) -> None:
        self._settings = settings or Settings()
        fixtures_root = Path(fixtures_dir or self._settings.fixtures_dir)
        self._fixtures = FixtureRepository(fixtures_root)
        self._configuration = self._load_search_configuration(fixtures_root)

        self._language = LanguageDetector(self._settings.allowed_langs)
        self._extractor = RulesExtractor(self._fixtures, self._configuration)
        self._normalizer = Normalizer(
            self._configuration,
            available_checkin_dates=self._fixtures.list_checkin_dates(),
        )
        self._validator = Validator(self._fixtures, self._configuration)

    def _load_search_configuration(self, fixtures_root: Path) -> SearchConfiguration:
        config_path = fixtures_root / self.CONFIG_FILENAME
        if not config_path.is_file():
            raise FileNotFoundError(f"Search configuration file '{config_path}' not found")
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Configuration fixture must be a JSON object")
        return SearchConfiguration.from_fixture_payload(payload)

    def run(self, utterance: str) -> Dict[str, Any]:
        detection = self._language.detect(utterance)
        extraction = self._extractor.extract(utterance)
        normalized = self._normalizer.normalize(detection.language, extraction)
        self._validator.validate(normalized)
        payload = normalized.to_payload()
        payload["status"] = "success"
        return payload

    @property
    def language_detector(self) -> LanguageDetector:
        """Expose the language detector for instrumentation consumers."""

        return self._language

    @property
    def extractor(self) -> RulesExtractor:
        """Expose the extractor instance for instrumentation consumers."""

        return self._extractor

    @property
    def normalizer(self) -> Normalizer:
        """Expose the normalizer instance for instrumentation consumers."""

        return self._normalizer

    @property
    def validator(self) -> Validator:
        """Expose the validator instance for instrumentation consumers."""

        return self._validator

    @property
    def fixtures(self) -> FixtureRepository:
        """Return the fixture repository backing the pipeline."""

        return self._fixtures

    @property
    def configuration(self) -> SearchConfiguration:
        """Return the search configuration used across the pipeline."""

        return self._configuration


__all__ = ["HolidaySearchPipeline", "SearchConfiguration"]
