"""Fixture repository and in-memory cache utilities."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple


class FixtureRepository:
    """Load and provide access to static fixture data.

    The repository eagerly reads JSON payloads from the fixtures directory,
    validates the expected schema, and caches lookups in convenient
    in-memory maps for downstream use.
    """

    AIRPORTS_FILE = "airports.json"
    DESTINATIONS_FILE = "destinations.json"
    DATES_FILE = "dates.json"
    VOCABULARY_FILE = "vocabulary_synonyms.json"

    def __init__(self, fixtures_dir: Path, *, encoding: str = "utf-8") -> None:
        self._fixtures_dir = Path(fixtures_dir)
        if not self._fixtures_dir.is_dir():
            raise FileNotFoundError(
                f"Fixture directory '{self._fixtures_dir}' does not exist or is not a directory"
            )
        self._encoding = encoding

        self._airports_by_id: Dict[str, Dict[str, Any]] = {}
        self._airports_by_name: Dict[str, str] = {}
        self._destinations_by_id: Dict[str, Dict[str, Any]] = {}
        self._destinations_by_name: Dict[str, str] = {}
        self._checkin_dates: List[str] = []
        self._locale_synonyms: Dict[str, Dict[str, Dict[str, str]]] = {}

        self._load_fixtures()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def get_airport_by_name(self, name: str) -> Dict[str, Any]:
        """Return airport metadata by name (case-insensitive)."""

        airport_id = self._get_id_from_name(name, self._airports_by_name, "airport")
        return self._airports_by_id[airport_id]

    def get_airport_by_id(self, identifier: str) -> Dict[str, Any]:
        """Return airport metadata by identifier."""

        if not isinstance(identifier, str) or not identifier.strip():
            raise KeyError("Airport identifier must be a non-empty string")
        key = identifier.strip().upper()
        try:
            return dict(self._airports_by_id[key])
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"Unknown airport id '{identifier}'") from exc

    def get_destination_by_name(self, name: str) -> Dict[str, Any]:
        """Return destination metadata by name (case-insensitive)."""

        destination_id = self._get_id_from_name(name, self._destinations_by_name, "destination")
        return self._destinations_by_id[destination_id]

    def get_destination_by_id(self, identifier: str) -> Dict[str, Any]:
        """Return destination metadata by identifier."""

        if not isinstance(identifier, str) or not identifier.strip():
            raise KeyError("Destination identifier must be a non-empty string")
        key = identifier.strip()
        try:
            return dict(self._destinations_by_id[key])
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"Unknown destination id '{identifier}'") from exc

    def list_checkin_dates(self) -> List[str]:
        """Return the sorted list of supported check-in dates."""

        return list(self._checkin_dates)

    def list_airports(self) -> List[Dict[str, Any]]:
        """Return metadata for all airports in the fixture set."""

        return [dict(meta) for meta in self._airports_by_id.values()]

    def list_destinations(self) -> List[Dict[str, Any]]:
        """Return metadata for all destinations in the fixture set."""

        return [dict(meta) for meta in self._destinations_by_id.values()]

    def locale_synonyms(self, category: Optional[str] = None) -> Dict[str, Dict[str, Dict[str, str]]]:
        """Return locale-specific synonym mappings for fixture entities."""

        if category is None:
            return {key: {lang: dict(values) for lang, values in mappings.items()} for key, mappings in self._locale_synonyms.items()}

        normalized = str(category).lower()
        mappings = self._locale_synonyms.get(normalized, {})
        return {lang: dict(values) for lang, values in mappings.items()}

    # ------------------------------------------------------------------
    # Loading and validation helpers
    # ------------------------------------------------------------------
    def _load_fixtures(self) -> None:
        airports_payload = self._load_json_payload(self.AIRPORTS_FILE)
        destinations_payload = self._load_json_payload(self.DESTINATIONS_FILE)
        dates_payload = self._load_json_payload(self.DATES_FILE)

        (
            self._airports_by_id,
            self._airports_by_name,
        ) = self._normalise_entity_payload(airports_payload, "data", "airports", required_keys={"id", "name"})

        (
            self._destinations_by_id,
            self._destinations_by_name,
        ) = self._normalise_entity_payload(
            destinations_payload,
            "data",
            "countries",
            required_keys={"id", "name"},
        )

        # The upstream payload uses the ``checkIns`` key for the list of dates.
        self._checkin_dates = self._normalise_dates_payload(dates_payload, "data", "checkIns")

        self._locale_synonyms = self._load_locale_synonyms()

    def _load_json_payload(self, filename: str) -> Dict[str, Any]:
        path = self._fixtures_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required fixture '{filename}' not found in '{self._fixtures_dir}'")
        try:
            text = path.read_text(encoding=self._encoding)
        except OSError as exc:
            raise FileNotFoundError(f"Unable to read fixture '{filename}': {exc}") from exc

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in fixture '{filename}': {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Fixture '{filename}' must contain a JSON object at the top level")
        return payload

    def _load_optional_json_payload(self, filename: str) -> Optional[Dict[str, Any]]:
        path = self._fixtures_dir / filename
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding=self._encoding)
        except OSError as exc:
            raise FileNotFoundError(f"Unable to read fixture '{filename}': {exc}") from exc

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in fixture '{filename}': {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Fixture '{filename}' must contain a JSON object at the top level")
        return payload

    def _normalise_entity_payload(
        self,
        payload: Dict[str, Any],
        top_level_key: str,
        collection_key: str,
        *,
        required_keys: Iterable[str],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        try:
            container = payload[top_level_key]
        except KeyError as exc:
            raise ValueError(f"Fixture missing top-level key '{top_level_key}'") from exc
        if not isinstance(container, dict):
            raise ValueError(f"Expected '{top_level_key}' to be a JSON object")

        try:
            items = container[collection_key]
        except KeyError as exc:
            raise ValueError(f"Fixture missing collection key '{top_level_key}.{collection_key}'") from exc
        if not isinstance(items, list):
            raise ValueError(f"Expected '{top_level_key}.{collection_key}' to be a list")

        by_id: Dict[str, Dict[str, Any]] = {}
        by_name: Dict[str, str] = {}
        required_keys = set(required_keys)

        for entry in items:
            if not isinstance(entry, dict):
                raise ValueError(f"Each entry in '{top_level_key}.{collection_key}' must be an object")

            missing = [key for key in required_keys if key not in entry or not str(entry[key]).strip()]
            if missing:
                raise ValueError(
                    f"Entries in '{top_level_key}.{collection_key}' are missing required fields: {', '.join(missing)}"
                )

            identifier = str(entry["id"]).strip()
            name = str(entry["name"]).strip()
            normalised_name = name.lower()

            if identifier in by_id:
                raise ValueError(f"Duplicate identifier '{identifier}' found in '{collection_key}'")
            if normalised_name in by_name:
                raise ValueError(f"Duplicate name '{name}' found in '{collection_key}'")

            metadata = dict(entry)
            metadata["id"] = identifier
            metadata["name"] = name

            by_id[identifier] = metadata
            by_name[normalised_name] = identifier

        return by_id, by_name

    def _normalise_dates_payload(self, payload: Dict[str, Any], top_level_key: str, collection_key: str) -> List[str]:
        try:
            container = payload[top_level_key]
        except KeyError as exc:
            raise ValueError(f"Fixture missing top-level key '{top_level_key}'") from exc
        if not isinstance(container, dict):
            raise ValueError(f"Expected '{top_level_key}' to be a JSON object")

        try:
            items = container[collection_key]
        except KeyError as exc:
            raise ValueError(f"Fixture missing collection key '{top_level_key}.{collection_key}'") from exc
        if not isinstance(items, list):
            raise ValueError(f"Expected '{top_level_key}.{collection_key}' to be a list")

        parsed_dates: List[Tuple[datetime, str]] = []
        for entry in items:
            if not isinstance(entry, dict):
                raise ValueError(f"Each entry in '{top_level_key}.{collection_key}' must be an object")
            if "date" not in entry:
                raise ValueError(f"Entries in '{top_level_key}.{collection_key}' must include a 'date' field")

            date_str = str(entry["date"]).strip()
            if not date_str:
                raise ValueError(f"Date entries in '{top_level_key}.{collection_key}' cannot be empty")
            try:
                parsed = datetime.strptime(date_str, "%d-%m-%Y")
            except ValueError as exc:
                raise ValueError(
                    f"Date '{date_str}' in '{top_level_key}.{collection_key}' is not in 'DD-MM-YYYY' format"
                ) from exc

            parsed_dates.append((parsed, date_str))

        parsed_dates.sort(key=lambda item: item[0])
        return [date_str for _, date_str in parsed_dates]

    def _load_locale_synonyms(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        payload = self._load_optional_json_payload(self.VOCABULARY_FILE)
        if payload is None:
            return {"airports": {}, "destinations": {}, "durations": {}, "flexibility": {}}

        airports = self._normalise_synonym_entries(
            payload.get("airports", []),
            label="airports",
            target_transform=str.upper,
            target_validator=lambda target: target in self._airports_by_id,
        )
        destinations = self._normalise_synonym_entries(
            payload.get("destinations", []),
            label="destinations",
            target_transform=lambda value: value.strip(),
            target_validator=lambda target: target in self._destinations_by_id,
        )
        durations = self._normalise_synonym_entries(
            payload.get("durations", []),
            label="durations",
            target_transform=lambda value: value.lower(),
            target_validator=None,
        )
        flexibility = self._normalise_synonym_entries(
            payload.get("flexibility", []),
            label="flexibility",
            target_transform=lambda value: value.lower(),
            target_validator=None,
        )

        return {
            "airports": airports,
            "destinations": destinations,
            "durations": durations,
            "flexibility": flexibility,
        }

    def _normalise_synonym_entries(
        self,
        entries: object,
        *,
        label: str,
        target_transform: Callable[[str], str] | None,
        target_validator: Callable[[str], bool] | None,
    ) -> Dict[str, Dict[str, str]]:
        if entries is None:
            return {}
        if not isinstance(entries, list):
            raise ValueError(f"Synonym fixture '{label}' must be provided as a list")

        result: Dict[str, Dict[str, str]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError(f"Synonym entries in '{label}' must be JSON objects")

            raw_target = str(entry.get("target", "")).strip()
            if not raw_target:
                raise ValueError(f"Synonym entries in '{label}' must include a 'target' field")

            target = target_transform(raw_target) if target_transform else raw_target
            if target_validator and not target_validator(target):
                raise ValueError(f"Synonym entry references unknown target '{raw_target}' in '{label}'")

            values = entry.get("values", [])
            if not isinstance(values, list):
                raise ValueError(f"Synonym entry '{raw_target}' in '{label}' must provide a list of values")

            for item in values:
                if not isinstance(item, Mapping):
                    raise ValueError(f"Synonym values in '{label}' must be JSON objects")

                lang = str(item.get("lang", "")).strip().lower()
                value = str(item.get("value", "")).strip().lower()
                if not lang or not value:
                    continue

                language_map = result.setdefault(lang, {})
                existing = language_map.get(value)
                if existing and existing != target:
                    raise ValueError(
                        f"Synonym '{value}' in '{label}' maps to multiple targets: '{existing}' and '{target}'"
                    )
                language_map[value] = target

        return result

    @staticmethod
    def _get_id_from_name(name: str, lookup: Dict[str, str], label: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise KeyError(f"{label.capitalize()} name must be a non-empty string")
        normalised = name.strip().lower()
        try:
            return lookup[normalised]
        except KeyError as exc:
            raise KeyError(f"Unknown {label} '{name}'") from exc
