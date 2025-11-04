"""Validation routines for normalized holiday search requests."""

from __future__ import annotations

from datetime import datetime

from ..fixtures.repository import FixtureRepository
from .normalizer import NormalizedResult
from .configuration import SearchConfiguration


class ValidationError(ValueError):
    """Custom error used when validation fails."""


class Validator:
    """Validate normalized payloads against fixture and configuration rules."""

    def __init__(self, fixtures: FixtureRepository, configuration: SearchConfiguration) -> None:
        self._config = configuration

        self._allowed_departure_dates = {
            datetime.strptime(value, "%d-%m-%Y").date().isoformat()
            for value in fixtures.list_checkin_dates()
        }

    def _validate_availability(self, normalized: NormalizedResult) -> None:
        for airport in normalized.context.get("airports", []):
            if not airport.get("available", False):
                raise ValidationError(f"Departure airport '{airport.get('name')}' is unavailable")
        for destination in normalized.context.get("destinations", []):
            if not destination.get("available", False):
                raise ValidationError(f"Destination '{destination.get('name')}' is unavailable")

    def _validate_multi_select_limits(self, normalized: NormalizedResult) -> None:
        airports_cfg = self._config.departure_airport
        destinations_cfg = self._config.destination_list

        if not airports_cfg.get("isMultiSelectAllowed") and len(normalized.from_codes) > 1:
            raise ValidationError("Multiple departure airports are not allowed")
        if len(normalized.from_codes) > airports_cfg.get("maxAllowedToSelect", float("inf")):
            raise ValidationError("Too many departure airports selected")

        if not destinations_cfg.get("isMultiSelectAllowed") and len(normalized.to_ids) > 1:
            raise ValidationError("Multiple destinations are not allowed")
        if len(normalized.to_ids) > destinations_cfg.get("maxAllowedToSelect", float("inf")):
            raise ValidationError("Too many destinations selected")

    def _validate_dates(self, normalized: NormalizedResult) -> None:
        if not normalized.departure_dates:
            raise ValidationError("Departure date is required")
        for iso_date in normalized.departure_dates:
            if iso_date not in self._allowed_departure_dates:
                raise ValidationError(f"Departure date '{iso_date}' is not available")

    def _validate_duration(self, normalized: NormalizedResult) -> None:
        if normalized.duration_id not in self._config.duration_by_id:
            raise ValidationError("Duration is not supported")

    def _validate_party(self, normalized: NormalizedResult) -> None:
        party_cfg = self._config.party
        adults = normalized.party.get("adults", 0)
        non_adults = normalized.party.get("nonAdults", 0)

        if adults < party_cfg.get("minAdultsPerBooking", 0):
            raise ValidationError("At least one adult is required")
        if adults > party_cfg.get("maxAdults", float("inf")):
            raise ValidationError("Too many adults requested")
        if non_adults > party_cfg.get("maxNonAdults", float("inf")):
            raise ValidationError("Too many children/infants requested")
        if adults == 0 and non_adults > 0:
            raise ValidationError("Children cannot travel without an adult")

    def _validate_rooms(self, normalized: NormalizedResult) -> None:
        rooms_cfg = self._config.rooms_configuration
        rooms = normalized.rooms
        if rooms is None and not rooms_cfg.get("autoRoomAllocationSwitch"):
            raise ValidationError("Number of rooms must be provided")
        if rooms is not None:
            if rooms < 1:
                raise ValidationError("At least one room must be requested")
            if rooms > rooms_cfg.get("maxNoOfRooms", float("inf")):
                raise ValidationError("Requested number of rooms exceeds the limit")

    def _validate_required_combinations(self, normalized: NormalizedResult) -> None:
        if not normalized.departure_dates:
            raise ValidationError("Departure date is required")

        combos = self._config.required_fields
        fields_present = {
            "from": bool(normalized.from_codes),
            "to": bool(normalized.to_ids),
            "departureDate": bool(normalized.departure_dates),
        }
        for combo in combos:
            if all(fields_present.get(field, False) for field in combo):
                return
        raise ValidationError("Utterance must include departure date with departure or destination")

    def validate(self, normalized: NormalizedResult) -> None:
        self._validate_availability(normalized)
        self._validate_multi_select_limits(normalized)
        self._validate_dates(normalized)
        self._validate_duration(normalized)
        self._validate_party(normalized)
        self._validate_rooms(normalized)
        self._validate_required_combinations(normalized)


__all__ = ["ValidationError", "Validator"]
