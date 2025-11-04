"""Normalisation routines for extracted holiday search parameters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence

from .extractor_rules import ExtractionResult

if TYPE_CHECKING:
    from .configuration import SearchConfiguration


@dataclass
class NormalizedResult:
    """Structured normalisation result consumed by downstream validators."""

    language: str
    from_codes: List[str]
    to_ids: List[str]
    departure_dates: List[str]
    duration_id: str
    party: Dict[str, int]
    rooms: Optional[int]
    context: Dict[str, object] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, object]:
        return {
            "language": self.language,
            "from": self.from_codes,
            "to": self.to_ids,
            "departureDate": self.departure_dates,
            "durationId": self.duration_id,
            "party": self.party,
            "rooms": self.rooms,
        }


class Normalizer:
    """Normalize extraction results to canonical representations."""

    def __init__(
        self,
        configuration: SearchConfiguration,
        *,
        available_checkin_dates: Sequence[str] | None = None,
    ) -> None:
        self._config = configuration
        self._available_dates = {
            datetime.strptime(date_str, "%d-%m-%Y").date().isoformat()
            for date_str in available_checkin_dates or []
            if isinstance(date_str, str) and date_str.strip()
        }

    def _normalize_dates(self, extraction: ExtractionResult) -> Dict[str, object]:
        if not extraction.dates:
            return {"dates": [], "base": None, "flex": None}

        phrase, dt = extraction.dates[0]
        base_date = dt.date()
        flex_option = extraction.flexibility or self._config.default_flex_option

        if not flex_option or not self._config.flexibility_allowed:
            return {
                "dates": [base_date.isoformat()],
                "base": base_date,
                "flex": None,
            }

        try:
            window_days = int(flex_option["id"])
        except (KeyError, TypeError, ValueError):
            window_days = 0

        if window_days <= 0:
            normalized = [base_date.isoformat()]
        else:
            start = base_date - timedelta(days=window_days)
            end = base_date + timedelta(days=window_days)
            start_iso = start.isoformat()
            end_iso = end.isoformat()

            if self._available_dates:
                candidates = sorted(
                    date_iso
                    for date_iso in self._available_dates
                    if start_iso <= date_iso <= end_iso
                )
                if len(candidates) > 1:
                    normalized = [candidates[0], candidates[-1]]
                elif candidates:
                    normalized = candidates
                else:
                    normalized = [base_date.isoformat()]
            else:
                normalized = [start_iso, end_iso]

        return {
            "dates": normalized,
            "base": base_date,
            "flex": flex_option,
        }

    def _normalize_airports(self, extraction: ExtractionResult) -> List[str]:
        codes: List[str] = []
        for airport in extraction.airports:
            code = str(airport.get("id", "")).upper()
            if code and code not in codes:
                codes.append(code)
        return codes

    def _normalize_destinations(self, extraction: ExtractionResult) -> List[str]:
        dests: List[str] = []
        for destination in extraction.destinations:
            identifier = str(destination.get("id", "")).strip()
            dest_type = str(destination.get("type", "")).strip().upper()
            if identifier:
                combined = f"{identifier}:{dest_type}" if dest_type else identifier
                if combined not in dests:
                    dests.append(combined)
        return dests

    def _normalize_duration(self, extraction: ExtractionResult) -> str:
        if extraction.duration:
            return str(extraction.duration.get("id", "")).strip() or self._config.default_duration_id
        return self._config.default_duration_id

    def _normalize_party(self) -> Dict[str, int]:
        defaults = self._config.defaults
        return {
            "adults": defaults.get("adults", 0),
            "nonAdults": defaults.get("nonAdults", 0),
        }

    def _normalize_rooms(self) -> Optional[int]:
        rooms_cfg = self._config.rooms_configuration
        if rooms_cfg.get("autoRoomAllocationSwitch"):
            return None
        return rooms_cfg.get("defaultNoOfRooms")

    def normalize(self, language: str, extraction: ExtractionResult) -> NormalizedResult:
        dates_info = self._normalize_dates(extraction)
        from_codes = self._normalize_airports(extraction)
        to_ids = self._normalize_destinations(extraction)
        duration_id = self._normalize_duration(extraction)
        party = self._normalize_party()
        rooms = self._normalize_rooms()

        context = {
            "airports": extraction.airports,
            "destinations": extraction.destinations,
            "dates_raw": extraction.dates,
            "dates_base": dates_info["base"],
            "flex_option": dates_info["flex"],
        }

        return NormalizedResult(
            language=language,
            from_codes=from_codes,
            to_ids=to_ids,
            departure_dates=dates_info["dates"],
            duration_id=duration_id,
            party=party,
            rooms=rooms,
            context=context,
        )


__all__ = ["NormalizedResult", "Normalizer"]
