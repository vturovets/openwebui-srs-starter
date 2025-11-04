"""Rule-based extractor that maps free text onto structured features."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dateparser.search import search_dates

from ..fixtures.repository import FixtureRepository

_DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": False,
}


@dataclass
class ExtractionResult:
    """Container for raw extraction signals."""

    airports: List[Dict[str, object]] = field(default_factory=list)
    destinations: List[Dict[str, object]] = field(default_factory=list)
    duration: Optional[Dict[str, object]] = None
    flexibility: Optional[Dict[str, object]] = None
    dates: List[Tuple[str, datetime]] = field(default_factory=list)

    def has_dates(self) -> bool:
        return bool(self.dates)


class RulesExtractor:
    """Heuristic extractor that relies on dictionaries and fixture configuration."""

    _DURATION_EXTRA_ALIASES = {
        "a week": "7 nights",
        "one week": "7 nights",
    }

    def __init__(self, fixtures: FixtureRepository, configuration: "SearchConfiguration") -> None:
        self._airports_by_name = {meta["name"].lower(): meta for meta in fixtures._airports_by_id.values()}  # type: ignore[attr-defined]
        self._destinations_by_name = {
            meta["name"].lower(): meta for meta in fixtures._destinations_by_id.values()  # type: ignore[attr-defined]
        }

        self._duration_lookup = configuration.duration_by_name
        self._flex_lookup = configuration.flex_by_name

    def _match_named_entities(self, lookup: Dict[str, Dict[str, object]], text: str) -> List[Dict[str, object]]:
        matches: List[Dict[str, object]] = []
        for name, meta in lookup.items():
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, text, flags=re.IGNORECASE):
                matches.append(meta)
        return matches

    def _extract_duration(self, text: str) -> Optional[Dict[str, object]]:
        lowered = text.lower()
        for alias, target in self._DURATION_EXTRA_ALIASES.items():
            if alias in lowered and target in self._duration_lookup:
                return self._duration_lookup[target]

        for name, entry in self._duration_lookup.items():
            if name in lowered:
                return entry
        return None

    def _extract_flexibility(self, text: str) -> Optional[Dict[str, object]]:
        lowered = text.lower()
        for name, entry in self._flex_lookup.items():
            if name in lowered:
                return entry
        return None

    def _extract_dates(self, text: str) -> List[Tuple[str, datetime]]:
        results: List[Tuple[str, datetime]] = []
        parsed = search_dates(text, settings=_DATEPARSER_SETTINGS) or []
        for phrase, dt in parsed:
            cleaned = phrase.strip().lower()
            if re.fullmatch(r"\d+\s+nights?", cleaned):
                continue
            if re.fullmatch(r"\d+", cleaned):
                continue
            results.append((phrase, dt))
        return results

    def extract(self, utterance: str) -> ExtractionResult:
        if not isinstance(utterance, str) or not utterance.strip():
            raise ValueError("Utterance must be a non-empty string for extraction")
        lowered = utterance.lower()

        airports = self._match_named_entities(self._airports_by_name, lowered)
        destinations = self._match_named_entities(self._destinations_by_name, lowered)
        duration = self._extract_duration(utterance)
        flexibility = self._extract_flexibility(utterance)
        dates = self._extract_dates(utterance)

        return ExtractionResult(
            airports=airports,
            destinations=destinations,
            duration=duration,
            flexibility=flexibility,
            dates=dates,
        )


__all__ = ["ExtractionResult", "RulesExtractor"]
