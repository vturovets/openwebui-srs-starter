"""Fixture repository and in-memory cache utilities."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


class FixtureRepository:
    """Load and provide access to static fixture data.

    The repository eagerly reads JSON payloads from the fixtures directory,
    validates the expected schema, and caches lookups in convenient
    in-memory maps for downstream use.
    """

    AIRPORTS_FILE = "airports.json"
    DESTINATIONS_FILE = "destinations.json"
    DATES_FILE = "dates.json"

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

        self._load_fixtures()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def get_airport_by_name(self, name: str) -> Dict[str, Any]:
        """Return airport metadata by name (case-insensitive)."""

        airport_id = self._get_id_from_name(name, self._airports_by_name, "airport")
        return self._airports_by_id[airport_id]

    def get_destination_by_name(self, name: str) -> Dict[str, Any]:
        """Return destination metadata by name (case-insensitive)."""

        destination_id = self._get_id_from_name(name, self._destinations_by_name, "destination")
        return self._destinations_by_id[destination_id]

    def list_checkin_dates(self) -> List[str]:
        """Return the sorted list of supported check-in dates."""

        return list(self._checkin_dates)

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

    @staticmethod
    def _get_id_from_name(name: str, lookup: Dict[str, str], label: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise KeyError(f"{label.capitalize()} name must be a non-empty string")
        normalised = name.strip().lower()
        try:
            return lookup[normalised]
        except KeyError as exc:
            raise KeyError(f"Unknown {label} '{name}'") from exc
