"""Rule-based extractor that maps free text onto structured features."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Mapping, Optional, Tuple

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
        airports_base: Dict[str, Dict[str, object]] = {}
        for meta in fixtures.list_airports():
            airports_base[meta["name"].lower()] = dict(meta)

        destinations_base: Dict[str, Dict[str, object]] = {}
        for meta in fixtures.list_destinations():
            destinations_base[meta["name"].lower()] = dict(meta)

        synonyms = fixtures.locale_synonyms()

        self._airports_lookup = self._build_entity_lookup(
            airports_base,
            synonyms.get("airports", {}),
            resolver=fixtures.get_airport_by_id,
        )
        self._destinations_lookup = self._build_entity_lookup(
            destinations_base,
            synonyms.get("destinations", {}),
            resolver=fixtures.get_destination_by_id,
        )

        duration_base = {name: dict(entry) for name, entry in configuration.duration_by_name.items()}
        flex_base = {name: dict(entry) for name, entry in configuration.flex_by_name.items()}

        self._duration_lookup_by_language = self._build_value_lookup(
            duration_base,
            synonyms.get("durations", {}),
        )
        self._flex_lookup_by_language = self._build_value_lookup(
            flex_base,
            synonyms.get("flexibility", {}),
        )

        # Augment English duration lookups with additional aliases.
        duration_en = self._duration_lookup_by_language.setdefault("en", dict(duration_base))
        for alias, target in self._DURATION_EXTRA_ALIASES.items():
            target_key = target.lower()
            if target_key in duration_base:
                duration_en[alias.lower()] = duration_base[target_key]

    def _build_entity_lookup(
        self,
        base: Dict[str, Dict[str, object]],
        synonyms: Dict[str, Dict[str, str]],
        *,
        resolver: Callable[[str], Mapping[str, object]],
    ) -> Dict[str, Dict[str, Dict[str, object]]]:
        base_lookup = {name: dict(meta) for name, meta in base.items()}
        lookups: Dict[str, Dict[str, Dict[str, object]]] = {"en": base_lookup}

        for language, mapping in synonyms.items():
            normalized_lang = language.lower()
            lang_lookup = dict(base_lookup)
            for alias, target in mapping.items():
                try:
                    resolved = resolver(target)
                except KeyError:
                    continue
                lang_lookup[alias.lower()] = dict(resolved)
            lookups[normalized_lang] = lang_lookup

        return lookups

    def _build_value_lookup(
        self,
        base: Dict[str, Dict[str, object]],
        synonyms: Dict[str, Dict[str, str]],
    ) -> Dict[str, Dict[str, Dict[str, object]]]:
        base_lookup = {name.lower(): dict(meta) for name, meta in base.items()}
        lookups: Dict[str, Dict[str, Dict[str, object]]] = {"en": dict(base_lookup)}

        for language, mapping in synonyms.items():
            normalized_lang = language.lower()
            lang_lookup = dict(base_lookup)
            for alias, target in mapping.items():
                entry = base_lookup.get(target.lower())
                if entry is None:
                    continue
                lang_lookup[alias.lower()] = entry
            lookups[normalized_lang] = lang_lookup

        return lookups

    def _match_named_entities(self, lookup: Dict[str, Dict[str, object]], text: str) -> List[Dict[str, object]]:
        matches: Dict[str, Dict[str, object]] = {}
        for name, meta in lookup.items():
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, text, flags=re.IGNORECASE):
                identifier = str(meta.get("id", ""))
                key = identifier or name
                if key not in matches:
                    matches[key] = dict(meta)
        return list(matches.values())

    def _extract_duration(self, text: str, language: str) -> Optional[Dict[str, object]]:
        lowered = text.lower()
        lookup = self._duration_lookup_by_language.get(language, self._duration_lookup_by_language["en"])
        for name, entry in lookup.items():
            if name in lowered:
                return dict(entry)
        return None

    def _extract_flexibility(self, text: str, language: str) -> Optional[Dict[str, object]]:
        lowered = text.lower()
        lookup = self._flex_lookup_by_language.get(language, self._flex_lookup_by_language["en"])
        for name, entry in lookup.items():
            if name in lowered:
                return dict(entry)
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
            if not any(char.isdigit() for char in cleaned):
                continue
            results.append((phrase, dt))
        return results

    def extract(self, utterance: str, *, language: str = "en") -> ExtractionResult:
        if not isinstance(utterance, str) or not utterance.strip():
            raise ValueError("Utterance must be a non-empty string for extraction")
        lowered = utterance.lower()
        language_key = (language or "en").lower()

        airport_lookup = self._airports_lookup.get(language_key, self._airports_lookup["en"])
        destination_lookup = self._destinations_lookup.get(language_key, self._destinations_lookup["en"])

        airports = self._match_named_entities(airport_lookup, lowered)
        destinations = self._match_named_entities(destination_lookup, lowered)
        duration = self._extract_duration(utterance, language_key)
        flexibility = self._extract_flexibility(utterance, language_key)
        dates = self._extract_dates(utterance)

        return ExtractionResult(
            airports=airports,
            destinations=destinations,
            duration=duration,
            flexibility=flexibility,
            dates=dates,
        )


__all__ = ["ExtractionResult", "RulesExtractor"]
