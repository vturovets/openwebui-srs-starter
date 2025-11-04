"""Pipeline orchestration and configuration helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..config import Settings
from ..fixtures.repository import FixtureRepository
from .extractor_rules import RulesExtractor
from .language import LanguageDetector
from .normalizer import Normalizer
from .validator import Validator


@dataclass(frozen=True)
class SearchConfiguration:
    """Wrapper around the search configuration fixture payload."""

    raw: Mapping[str, Any]

    @property
    def defaults(self) -> Mapping[str, int]:
        return self.raw.get("defaults", {})

    @property
    def party(self) -> Mapping[str, Any]:
        return self.raw.get("party", {})

    @property
    def departure_airport(self) -> Mapping[str, Any]:
        return self.raw.get("departureAirport", {})

    @property
    def destination_list(self) -> Mapping[str, Any]:
        return self.raw.get("destinationList", {})

    @property
    def rooms_configuration(self) -> Mapping[str, Any]:
        return self.raw.get("roomsConfiguration", {})

    @property
    def durations(self) -> List[Mapping[str, Any]]:
        return list(self.raw.get("durations", []))

    @property
    def flexibility(self) -> Mapping[str, Any]:
        return self.raw.get("flexibility", {})

    @property
    def required_fields(self) -> List[List[str]]:
        return [list(combo) for combo in self.raw.get("requiredFieldsForSearch", [])]

    @property
    def duration_by_name(self) -> Dict[str, Mapping[str, Any]]:
        return {str(entry.get("name", "")).lower(): entry for entry in self.durations}

    @property
    def duration_by_id(self) -> Dict[str, Mapping[str, Any]]:
        return {str(entry.get("id", "")): entry for entry in self.durations}

    @property
    def default_duration_id(self) -> str:
        for entry in self.durations:
            if entry.get("isDefault"):
                return str(entry.get("id", ""))
        return self.durations[0].get("id", "") if self.durations else ""

    @property
    def flex_options(self) -> List[Mapping[str, Any]]:
        return list(self.flexibility.get("flexibleList", []))

    @property
    def flex_by_name(self) -> Dict[str, Mapping[str, Any]]:
        return {str(entry.get("name", "")).lower(): entry for entry in self.flex_options}

    @property
    def flex_by_id(self) -> Dict[str, Mapping[str, Any]]:
        return {str(entry.get("id", "")): entry for entry in self.flex_options}

    @property
    def default_flex_option(self) -> Optional[Mapping[str, Any]]:
        if not self.flexibility_allowed:
            return None
        for entry in self.flex_options:
            if entry.get("isDefault"):
                return entry
        return self.flex_options[0] if self.flex_options else None

    @property
    def flexibility_allowed(self) -> bool:
        return bool(self.flexibility.get("isFlexibleAllowed", False))

    @classmethod
    def from_fixture_payload(cls, payload: Mapping[str, Any]) -> "SearchConfiguration":
        try:
            config = payload["holidaySearchConfiguration"]
        except KeyError as exc:
            raise ValueError("Invalid configuration payload: missing 'holidaySearchConfiguration'") from exc
        if not isinstance(config, Mapping):
            raise TypeError("Configuration payload must provide a mapping")
        return cls(raw=config)


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
        self._normalizer = Normalizer(self._configuration)
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
