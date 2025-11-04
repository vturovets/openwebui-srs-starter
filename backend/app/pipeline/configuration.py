"""Search configuration model used across pipeline components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional


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


__all__ = ["SearchConfiguration"]
