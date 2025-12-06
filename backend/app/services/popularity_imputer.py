"""Popularity-based imputation service for underspecified search params."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Mapping, MutableMapping, Sequence, Tuple

from ..config import Settings
from ..pipeline.configuration import SearchConfiguration

logger = logging.getLogger(__name__)


class PopularityImputer:
    """Fill missing search parameters using historic popularity statistics."""

    CONFIG_FILENAME = "configuration_search.json"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        configuration: SearchConfiguration | None = None,
        stats_payload: Mapping[str, object] | None = None,
        stats_path: Path | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._enabled = bool(self._settings.popularity_imputer_enabled)
        self._stats_path = Path(stats_path or self._settings.popularity_data_path)
        self._configuration = configuration or self._load_configuration()

        payload = stats_payload or self._load_statistics()
        self._stats: Mapping[str, object] = payload or {}
        self._global_stats: Mapping[str, object] = self._stats.get("global", {}) if payload else {}
        destinations = self._stats.get("destinations", {}) if payload else {}
        intersections = self._stats.get("intersections", {}) if payload else {}

        self._destination_stats: Dict[str, Mapping[str, object]] = {}
        self._destination_names: Dict[str, str] = {}
        if isinstance(destinations, Mapping):
            for name, summary in destinations.items():
                if not isinstance(name, str) or not isinstance(summary, Mapping):
                    continue
                key = name.strip().lower()
                self._destination_stats[key] = summary
                self._destination_names[key] = name.strip()

        self._intersection_stats: Dict[Tuple[str, ...], Mapping[str, object]] = {}
        self._intersection_labels: Dict[Tuple[str, ...], str] = {}
        if isinstance(intersections, Mapping):
            for label, summary in intersections.items():
                if not isinstance(summary, Mapping):
                    continue
                destinations_list = summary.get("destinations")
                if isinstance(destinations_list, Sequence) and destinations_list:
                    normalized = [str(item).strip().lower() for item in destinations_list if str(item).strip()]
                else:
                    normalized = [segment.strip().lower() for segment in str(label).split("||") if segment.strip()]
                if not normalized:
                    continue
                key = tuple(sorted(normalized))
                self._intersection_stats[key] = summary
                label_values = summary.get("destinations")
                if isinstance(label_values, Sequence) and label_values:
                    pretty = [str(item).strip() for item in label_values if str(item).strip()]
                    label_value = "||".join(pretty) if pretty else "||".join(normalized)
                else:
                    label_value = "||".join(normalized)
                self._intersection_labels[key] = label_value

        self._duration_id_by_numeric = self._build_duration_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def impute(self, params: Mapping[str, object]) -> tuple[dict, dict]:
        """Augment ``params`` with popular defaults when fields are missing."""

        if not isinstance(params, Mapping):
            raise TypeError("params must be a mapping")

        payload = dict(params)
        metadata: Dict[str, object] = {"enabled": self._enabled, "imputed": {}}
        imputed_meta: MutableMapping[str, dict] = metadata["imputed"]  # type: ignore[assignment]

        if not self._enabled or not self._stats:
            return payload, metadata

        allow_intersection = bool(payload.pop("allowIntersection", True))

        request_was_unpopulated = self._is_unpopulated_request(payload)

        if request_was_unpopulated:
            popular_destination = self._select_most_popular_destination()
            if popular_destination:
                payload["to"] = [popular_destination]
                imputed_meta["to"] = {"source": "popularity", "value": popular_destination}

        destinations, missing_destinations = self._extract_destinations(payload.get("to"))
        if missing_destinations:
            metadata["destinationsWithoutStats"] = missing_destinations

        if self._needs_duration(payload):
            duration_id, source = self._select_duration_id(destinations)
            if duration_id:
                payload["durationId"] = duration_id
                imputed_meta["durationId"] = {"source": source, "value": duration_id}

        if self._needs_party(payload):
            party, source = self._select_party(destinations)
            if party:
                payload["party"] = party
                imputed_meta["party"] = {"source": source, "value": dict(party)}

        if self._needs_rooms(payload):
            rooms, source = self._select_rooms(
                destinations, allow_auto_configuration=not request_was_unpopulated
            )
            payload["rooms"] = rooms
            rooms_meta = {"source": source, "autoRoomAllocationSwitch": self._auto_room_enabled}
            rooms_meta["value"] = rooms
            imputed_meta["rooms"] = rooms_meta

        if self._needs_departure_airport(payload):
            airport, source = self._select_departure_airport(destinations)
            if airport:
                payload["from"] = [airport]
                imputed_meta["from"] = {"source": source, "value": airport}

        if self._needs_departure_date(payload):
            interval, source = self._select_interval(
                destinations, allow_intersection=allow_intersection
            )
            if interval:
                payload["departureDate"] = [interval[0]]
                imputed_meta["departureDate"] = {
                    "source": source,
                    "interval": {"start": interval[0], "end": interval[1]},
                    "value": interval[0],
                }

        return payload, metadata

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------
    @property
    def _auto_room_enabled(self) -> bool:
        cfg = self._configuration.rooms_configuration
        return bool(cfg.get("autoRoomAllocationSwitch"))

    def _needs_duration(self, payload: Mapping[str, object]) -> bool:
        value = payload.get("durationId")
        return not isinstance(value, str) or not value.strip()

    def _needs_party(self, payload: Mapping[str, object]) -> bool:
        value = payload.get("party")
        if not isinstance(value, Mapping):
            return True
        return "adults" not in value or "nonAdults" not in value

    def _needs_rooms(self, payload: Mapping[str, object]) -> bool:
        return "rooms" not in payload or payload.get("rooms") in (None, 0)

    def _needs_departure_airport(self, payload: Mapping[str, object]) -> bool:
        value = payload.get("from")
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, Sequence):
            return len(value) == 0
        return True

    def _needs_departure_date(self, payload: Mapping[str, object]) -> bool:
        value = payload.get("departureDate")
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, Sequence):
            return len(value) == 0
        return True

    def _is_unpopulated_request(self, payload: Mapping[str, object]) -> bool:
        def _missing(value: object) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                return not value.strip()
            if isinstance(value, Mapping):
                return len(value) == 0
            if isinstance(value, Sequence):
                return len(value) == 0
            return False

        return all(
            _missing(payload.get(field))
            for field in ("to", "from", "departureDate", "durationId", "party", "rooms")
        )

    def _select_duration_id(self, destinations: Sequence[str]) -> tuple[str | None, str]:
        destination_mode = self._select_from_destinations(destinations, "duration")
        if destination_mode:
            mapped = self._map_duration_value(destination_mode[0])
            if mapped:
                return mapped, destination_mode[1]
        global_mode = self._extract_mode(self._global_stats.get("duration"))
        if global_mode is not None:
            mapped = self._map_duration_value(global_mode)
            if mapped:
                return mapped, "global"
        return self._configuration.default_duration_id, "configuration"

    def _select_party(self, destinations: Sequence[str]) -> tuple[dict | None, str]:
        destination_mode = self._select_from_destinations(destinations, "party")
        if destination_mode:
            converted = self._convert_party(destination_mode[0])
            if converted:
                return converted, destination_mode[1]
        global_mode = self._extract_mode(self._global_stats.get("party"))
        if global_mode is not None:
            converted = self._convert_party(global_mode)
            if converted:
                return converted, "global"
        defaults = self._configuration.defaults
        return {
            "adults": int(defaults.get("adults", 0) or 0),
            "nonAdults": int(defaults.get("nonAdults", 0) or 0),
        }, "configuration"

    def _select_rooms(
        self, destinations: Sequence[str], *, allow_auto_configuration: bool = True
    ) -> tuple[int | None, str]:
        if self._auto_room_enabled and allow_auto_configuration:
            return None, "configuration"
        destination_mode = self._select_from_destinations(destinations, "rooms")
        if destination_mode and self._is_valid_room_value(destination_mode[0]):
            return int(destination_mode[0]), destination_mode[1]
        global_mode = self._extract_mode(self._global_stats.get("rooms"))
        if self._is_valid_room_value(global_mode):
            return int(global_mode), "global"
        rooms_cfg = self._configuration.rooms_configuration
        default_rooms = rooms_cfg.get("defaultNoOfRooms")
        if isinstance(default_rooms, int) and default_rooms > 0:
            return default_rooms, "configuration"
        return 1, "configuration"

    def _select_departure_airport(self, destinations: Sequence[str]) -> tuple[str | None, str]:
        destination_mode = self._select_from_destinations(destinations, "departure_airport")
        if destination_mode:
            airport = self._normalize_airport(destination_mode[0])
            if airport:
                return airport, destination_mode[1]
        global_mode = self._extract_mode(self._global_stats.get("departure_airport"))
        if isinstance(global_mode, str) and global_mode.strip():
            return global_mode.strip(), "global"
        return None, "configuration"

    def _select_most_popular_destination(self) -> str | None:
        global_mode = self._extract_mode(self._global_stats.get("destination"))
        if isinstance(global_mode, str) and global_mode.strip():
            normalized = global_mode.strip().lower()
            return self._destination_names.get(normalized, global_mode.strip())

        if not self._destination_stats:
            return None

        def _metric_total(summary: Mapping[str, object]) -> int:
            if not isinstance(summary, Mapping):
                return 0
            value = summary.get("total")
            try:
                return int(value) if value is not None else 0
            except (TypeError, ValueError):
                return 0

        best_label: str | None = None
        best_total = -1
        best_mode_count = -1

        for key, summary in self._destination_stats.items():
            duration_summary = summary.get("duration") if isinstance(summary, Mapping) else None
            total = _metric_total(duration_summary or {})
            mode_count = 0
            if isinstance(duration_summary, Mapping):
                mode_count_value = duration_summary.get("mode_count")
                try:
                    mode_count = int(mode_count_value) if mode_count_value is not None else 0
                except (TypeError, ValueError):
                    mode_count = 0

            label = self._destination_names.get(key, key)
            if (
                total > best_total
                or (total == best_total and mode_count > best_mode_count)
                or (
                    total == best_total
                    and mode_count == best_mode_count
                    and best_label is not None
                    and label < best_label
                )
            ):
                best_total = total
                best_mode_count = mode_count
                best_label = label

        return best_label

    def _select_interval(
        self, destinations: Sequence[str], *, allow_intersection: bool = True
    ) -> tuple[tuple[str, str] | None, str]:
        if not destinations:
            interval = self._extract_interval(self._global_stats.get("interval"))
            if interval:
                return interval, "global"
            return None, "configuration"

        if len(destinations) == 1:
            stats = self._destination_stats.get(destinations[0].lower())
            interval = self._extract_interval(stats.get("interval")) if stats else None
            if interval:
                return interval, f"destination:{destinations[0]}"
            interval = self._extract_interval(self._global_stats.get("interval"))
            if interval:
                return interval, "global"
            return None, "configuration"

        if allow_intersection:
            normalized = tuple(
                sorted(dest.lower() for dest in destinations if dest.lower() in self._destination_stats)
            )
            if normalized:
                combo = self._intersection_stats.get(normalized)
                if combo:
                    interval = self._extract_interval(combo)
                    if interval:
                        label = self._intersection_labels.get(normalized, "||".join(destinations))
                        return interval, f"intersection:{label}"
        interval = self._extract_interval(self._global_stats.get("interval"))
        if interval:
            return interval, "global"
        return None, "configuration"

    def _select_from_destinations(self, destinations: Sequence[str], metric: str) -> tuple[object, str] | None:
        for dest in destinations:
            stats = self._destination_stats.get(dest.lower())
            if not stats:
                continue
            summary = stats.get(metric)
            mode = self._extract_mode(summary)
            if mode is not None:
                return mode, f"destination:{dest}"
        return None

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------
    def _extract_destinations(self, raw_value: object) -> tuple[list[str], list[str]]:
        if isinstance(raw_value, Mapping):
            candidates = [raw_value]
        elif isinstance(raw_value, Sequence) and not isinstance(raw_value, str):
            candidates = list(raw_value)
        elif raw_value is None:
            candidates = []
        else:
            candidates = [raw_value]

        resolved: list[str] = []
        missing: list[str] = []
        seen: set[str] = set()

        for entry in candidates:
            if isinstance(entry, Mapping):
                candidate = entry.get("name") or entry.get("id")
            else:
                candidate = entry
            if not isinstance(candidate, str):
                continue
            base = candidate.strip()
            if not base:
                continue
            normalized = base.split(":", 1)[0].strip()
            lowered = normalized.lower()
            canonical = self._destination_names.get(lowered, normalized)
            canonical_lower = canonical.lower()
            if canonical_lower not in seen:
                seen.add(canonical_lower)
                resolved.append(canonical)
            if lowered not in self._destination_stats:
                if normalized not in missing:
                    logger.warning("Popularity statistics not found for destination '%s'", normalized)
                    missing.append(normalized)
        return resolved, missing

    def _extract_mode(self, summary: object) -> object | None:
        if not isinstance(summary, Mapping):
            return None
        mode = summary.get("mode")
        if mode is not None and (not isinstance(mode, str) or mode.strip()):
            return mode
        top_values = summary.get("top_values") or summary.get("top_intervals")
        if isinstance(top_values, Sequence):
            for entry in top_values:
                if not isinstance(entry, Mapping):
                    continue
                value = entry.get("value")
                if value is not None and (not isinstance(value, str) or value.strip()):
                    return value
        return None

    def _extract_interval(self, summary: object) -> tuple[str, str] | None:
        if not isinstance(summary, Mapping):
            return None
        mode = summary.get("mode")
        interval = self._parse_interval(mode)
        if interval:
            return interval
        top_values = summary.get("top_values") or summary.get("top_intervals")
        if isinstance(top_values, Sequence):
            for entry in top_values:
                if not isinstance(entry, Mapping):
                    continue
                interval = self._parse_interval(entry.get("value"))
                if interval:
                    return interval
        return None

    def _parse_interval(self, payload: object) -> tuple[str, str] | None:
        if not isinstance(payload, Mapping):
            return None
        start = payload.get("start")
        end = payload.get("end")
        if isinstance(start, str) and isinstance(end, str) and start and end:
            return (start, end)
        return None

    def _convert_party(self, payload: object) -> dict | None:
        if not isinstance(payload, Mapping):
            return None
        adults = payload.get("adults")
        children = payload.get("children")
        infants = payload.get("infants")
        if adults is None:
            return None
        return {
            "adults": int(adults or 0),
            "nonAdults": int(children or 0) + int(infants or 0),
        }

    def _map_duration_value(self, value: object) -> str | None:
        if value is None:
            return None
        value_str = str(value).strip()
        if not value_str:
            return None
        if value_str in self._duration_id_by_numeric.values():
            return value_str
        try:
            numeric = int(value_str)
        except ValueError:
            return None
        return self._duration_id_by_numeric.get(numeric)

    def _normalize_airport(self, value: object) -> str | None:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return None

    def _is_valid_room_value(self, value: object | None) -> bool:
        if value is None:
            return False
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return False
        return parsed > 0

    def _build_duration_index(self) -> Dict[int, str]:
        mapping: Dict[int, str] = {}
        for entry in self._configuration.durations:
            identifier = str(entry.get("id", "")).strip()
            if not identifier:
                continue
            name = str(entry.get("name", ""))
            numeric = self._extract_numeric_prefix(name)
            if numeric is not None:
                mapping[numeric] = identifier
        return mapping

    def _extract_numeric_prefix(self, label: str) -> int | None:
        digits = ""
        for char in label:
            if char.isdigit():
                digits += char
            elif digits:
                break
        if digits:
            return int(digits)
        return None

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------
    def _load_configuration(self) -> SearchConfiguration:
        config_path = Path(self._settings.fixtures_dir) / self.CONFIG_FILENAME
        if not config_path.is_file():
            raise FileNotFoundError(f"Search configuration fixture '{config_path}' not found")
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Configuration fixture must be a JSON object")
        return SearchConfiguration.from_fixture_payload(payload)

    def _load_statistics(self) -> Mapping[str, object] | None:
        if self._stats_path.is_file():
            text = self._stats_path.read_text(encoding="utf-8")
            return json.loads(text)
        logger.warning(
            "Popularity statistics file '%s' not found; attempting to rebuild from %s",
            self._stats_path,
            self._settings.popularity_source_csv_path,
        )
        rebuilt = self._rebuild_statistics()
        if rebuilt:
            return rebuilt
        logger.error("Unable to load popularity statistics; imputer will remain disabled")
        self._enabled = False
        return None

    def _rebuild_statistics(self) -> Mapping[str, object] | None:
        csv_path = Path(self._settings.popularity_source_csv_path)
        if not csv_path.is_file():
            logger.error("Popularity CSV '%s' not found; cannot rebuild statistics", csv_path)
            return None
        try:
            from scripts import build_popularity_stats as builder
        except ImportError as exc:  # pragma: no cover - defensive
            logger.error("Unable to import builder for popularity stats: %s", exc)
            return None
        rows = list(builder.read_rows(csv_path))
        global_summary, destination_summary, intersection_summary = builder.build_statistics(rows, top_n=builder.DEFAULT_TOP_N)
        metadata = {
            "schema_version": builder.SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "path": str(csv_path),
                "sha256": builder.compute_sha256(csv_path),
                "rows": global_summary.get("totals", {}).get("rows", 0),
            },
            "top_n": builder.DEFAULT_TOP_N,
            "generator": "scripts.build_popularity_stats",
        }
        payload = {
            "metadata": metadata,
            "global": global_summary,
            "destinations": destination_summary,
            "intersections": intersection_summary,
        }
        try:
            self._stats_path.parent.mkdir(parents=True, exist_ok=True)
            self._stats_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError as exc:
            logger.warning("Failed to persist rebuilt popularity statistics: %s", exc)
        return payload


__all__ = ["PopularityImputer"]
