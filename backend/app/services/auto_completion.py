"""Auto-completion suggestions powered by popularity statistics."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from ..fixtures.repository import FixtureRepository
from ..pipeline.configuration import SearchConfiguration

logger = logging.getLogger(__name__)


class AutoCompletionService:
    """Return structured suggestions derived from popularity statistics."""

    TOKEN_PATTERN = re.compile(r"[\w']+")

    def __init__(
        self,
        fixtures: FixtureRepository,
        configuration: SearchConfiguration,
        *,
        stats_payload: Mapping[str, object] | None = None,
        stats_path: Path | None = None,
    ) -> None:
        self._fixtures = fixtures
        self._configuration = configuration
        self._stats_path = Path(stats_path) if stats_path else None

        payload = stats_payload or self._load_statistics()
        if not isinstance(payload, Mapping):
            payload = {}
        self._stats: Mapping[str, object] = payload
        self._global_stats: Mapping[str, object] = self._stats.get("global", {}) if payload else {}
        destinations_stats = self._stats.get("destinations", {}) if payload else {}
        intersections_stats = self._stats.get("intersections", {}) if payload else {}

        self._destination_id_to_name: Dict[str, str] = {}
        self._destination_candidates: Dict[str, List[str]] = {}
        self._destination_frequency: Dict[str, int] = {}
        self._destination_stats: Dict[str, Mapping[str, object]] = {}
        self._destination_order: List[str] = []

        self._airport_id_to_name: Dict[str, str] = {}
        self._airport_candidates: Dict[str, List[str]] = {}
        self._airport_frequency: Dict[str, int] = {}
        self._airport_order: List[str] = []

        self._intersection_stats: Dict[tuple[str, ...], Mapping[str, object]] = {}
        self._intersection_labels: Dict[tuple[str, ...], str] = {}

        self._build_destination_indexes(destinations_stats)
        self._build_airport_indexes()
        self._build_intersection_index(intersections_stats)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def suggest(self, partial_query: str, limit: int = 3) -> Dict[str, List[Dict[str, object]]]:
        """Return suggestions for each supported search field."""

        safe_limit = max(1, int(limit or 1))
        tokens = self._tokenize(partial_query or "")
        normalized_query = (partial_query or "").lower()

        context_destinations = self._detect_destinations(normalized_query, tokens, max(safe_limit * 2, 5))

        payload: Dict[str, List[Dict[str, object]]] = {
            "destinations": self._build_destination_suggestions(tokens, safe_limit),
            "departureDates": self._build_departure_date_suggestions(context_destinations, safe_limit),
            "durations": self._build_duration_suggestions(context_destinations, safe_limit),
            "party": self._build_party_suggestions(context_destinations, safe_limit),
            "rooms": self._build_room_suggestions(context_destinations, safe_limit),
            "from": self._build_departure_airport_suggestions(context_destinations, tokens, safe_limit),
        }
        return payload

    # ------------------------------------------------------------------
    # Suggestion builders
    # ------------------------------------------------------------------
    def _build_destination_suggestions(self, tokens: Sequence[str], limit: int) -> List[Dict[str, object]]:
        matches = self._match_by_tokens(tokens, self._destination_order, self._destination_candidates)
        if not matches:
            matches = list(self._destination_order)
        suggestions = [{"value": name} for name in matches[:limit]]
        return suggestions

    def _build_departure_date_suggestions(
        self, destinations: Sequence[str], limit: int
    ) -> List[Dict[str, object]]:
        suggestions: List[Dict[str, object]] = []
        normalized = sorted({self._normalize(value) for value in destinations if value})

        if len(normalized) >= 2:
            key = tuple(normalized)
            summary = self._intersection_stats.get(key)
            if summary:
                label = self._intersection_labels.get(key, "intersection")
                for entry in summary.get("top_intervals", []):
                    interval = entry.get("value") if isinstance(entry, Mapping) else None
                    if not isinstance(interval, Mapping):
                        continue
                    suggestion = {
                        "start": interval.get("start"),
                        "end": interval.get("end"),
                        "source": "intersection",
                        "label": label,
                    }
                    if suggestion["start"] and suggestion["end"]:
                        suggestions.append(suggestion)
                if suggestions:
                    return suggestions[:limit]

        for destination in destinations:
            stats = self._destination_stats.get(self._normalize(destination))
            if not isinstance(stats, Mapping):
                continue
            for entry in self._extract_top_values(stats.get("interval")):
                interval = entry.get("value") if isinstance(entry, Mapping) else None
                if not isinstance(interval, Mapping):
                    continue
                suggestion = {
                    "start": interval.get("start"),
                    "end": interval.get("end"),
                    "source": destination,
                }
                if suggestion["start"] and suggestion["end"]:
                    suggestions.append(suggestion)
                    if len(suggestions) >= limit:
                        return suggestions

        for entry in self._extract_top_values(self._global_stats.get("interval")):
            interval = entry.get("value") if isinstance(entry, Mapping) else None
            if not isinstance(interval, Mapping):
                continue
            suggestion = {
                "start": interval.get("start"),
                "end": interval.get("end"),
                "source": "global",
            }
            if suggestion["start"] and suggestion["end"]:
                suggestions.append(suggestion)
                if len(suggestions) >= limit:
                    break

        return suggestions[:limit]

    def _build_duration_suggestions(self, destinations: Sequence[str], limit: int) -> List[Dict[str, object]]:
        return self._collect_numeric_suggestions(destinations, limit, key="duration", label="nights")

    def _build_party_suggestions(self, destinations: Sequence[str], limit: int) -> List[Dict[str, object]]:
        suggestions: List[Dict[str, object]] = []
        seen: set[tuple[int, int]] = set()

        for source, entry in self._iterate_stat_values(destinations, "party"):
            value = entry.get("value") if isinstance(entry, Mapping) else None
            if not isinstance(value, Mapping):
                continue
            adults = int(value.get("adults", 0) or 0)
            children = int(value.get("children", 0) or 0)
            infants = int(value.get("infants", 0) or 0)
            non_adults = max(children + infants, 0)
            key = (adults, non_adults)
            if key in seen:
                continue
            seen.add(key)
            suggestions.append({
                "value": {"adults": adults, "nonAdults": non_adults},
                "source": source,
            })
            if len(suggestions) >= limit:
                return suggestions

        for entry in self._extract_top_values(self._global_stats.get("party")):
            value = entry.get("value") if isinstance(entry, Mapping) else None
            if not isinstance(value, Mapping):
                continue
            adults = int(value.get("adults", 0) or 0)
            children = int(value.get("children", 0) or 0)
            infants = int(value.get("infants", 0) or 0)
            non_adults = max(children + infants, 0)
            key = (adults, non_adults)
            if key in seen:
                continue
            seen.add(key)
            suggestions.append({
                "value": {"adults": adults, "nonAdults": non_adults},
                "source": "global",
            })
            if len(suggestions) >= limit:
                break

        return suggestions[:limit]

    def _build_room_suggestions(self, destinations: Sequence[str], limit: int) -> List[Dict[str, object]]:
        rooms_config = self._configuration.rooms_configuration
        if bool(rooms_config.get("autoRoomAllocationSwitch")):
            return []

        return self._collect_numeric_suggestions(destinations, limit, key="rooms", label="rooms")

    def _build_departure_airport_suggestions(
        self, destinations: Sequence[str], tokens: Sequence[str], limit: int
    ) -> List[Dict[str, object]]:
        matches = self._match_by_tokens(tokens, self._airport_order, self._airport_candidates)
        suggestions: List[Dict[str, object]] = []
        seen: set[str] = set()

        for airport in matches:
            if airport in seen:
                continue
            seen.add(airport)
            suggestions.append({"value": airport, "source": "text"})
            if len(suggestions) >= limit:
                return suggestions

        for source, entry in self._iterate_stat_values(destinations, "departure_airport"):
            value = entry.get("value") if isinstance(entry, Mapping) else None
            airport_name = value if isinstance(value, str) else None
            if not airport_name or airport_name in seen:
                continue
            seen.add(airport_name)
            suggestions.append({"value": airport_name, "source": source})
            if len(suggestions) >= limit:
                return suggestions

        for entry in self._extract_top_values(self._global_stats.get("departure_airport")):
            airport_name = entry.get("value") if isinstance(entry, Mapping) else None
            if not isinstance(airport_name, str) or airport_name in seen:
                continue
            seen.add(airport_name)
            suggestions.append({"value": airport_name, "source": "global"})
            if len(suggestions) >= limit:
                break

        return suggestions[:limit]

    # ------------------------------------------------------------------
    # Matching helpers
    # ------------------------------------------------------------------
    def _detect_destinations(
        self, normalized_query: str, tokens: Sequence[str], max_items: int
    ) -> List[str]:
        matches: List[str] = []
        seen: set[str] = set()

        for name in self._destination_order:
            candidates = self._destination_candidates.get(name, [])
            if any(value in normalized_query for value in candidates):
                if name not in seen:
                    matches.append(name)
                    seen.add(name)
            elif tokens and self._matches_tokens(tokens, candidates):
                if name not in seen:
                    matches.append(name)
                    seen.add(name)
            if len(matches) >= max_items:
                break

        return matches

    def _match_by_tokens(
        self,
        tokens: Sequence[str],
        ordered_values: Sequence[str],
        candidates: Mapping[str, Sequence[str]],
    ) -> List[str]:
        if not tokens:
            return list(ordered_values)

        matches: List[str] = []
        seen: set[str] = set()
        for name in ordered_values:
            if name in seen:
                continue
            options = candidates.get(name, [])
            if self._matches_tokens(tokens, options):
                matches.append(name)
                seen.add(name)
        return matches

    def _matches_tokens(self, tokens: Sequence[str], candidates: Sequence[str]) -> bool:
        for token in tokens:
            if not token:
                continue
            for candidate in candidates:
                if token in candidate:
                    return True
        return False

    def _tokenize(self, text: str) -> List[str]:
        return [match.group(0).lower() for match in self.TOKEN_PATTERN.finditer(text)]

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------
    def _collect_numeric_suggestions(
        self, destinations: Sequence[str], limit: int, *, key: str, label: str
    ) -> List[Dict[str, object]]:
        suggestions: List[Dict[str, object]] = []
        seen: set[str] = set()

        for source, entry in self._iterate_stat_values(destinations, key):
            value = entry.get("value") if isinstance(entry, Mapping) else None
            if value in (None, ""):
                continue
            normalized = str(value)
            if normalized in seen:
                continue
            seen.add(normalized)
            payload = {"value": normalized, "source": source}
            if label == "nights":
                payload["label"] = f"{normalized} {label}"
            suggestions.append(payload)
            if len(suggestions) >= limit:
                return suggestions

        for entry in self._extract_top_values(self._global_stats.get(key)):
            value = entry.get("value") if isinstance(entry, Mapping) else None
            if value in (None, ""):
                continue
            normalized = str(value)
            if normalized in seen:
                continue
            seen.add(normalized)
            payload = {"value": normalized, "source": "global"}
            if label == "nights":
                payload["label"] = f"{normalized} {label}"
            suggestions.append(payload)
            if len(suggestions) >= limit:
                break

        return suggestions[:limit]

    def _iterate_stat_values(
        self, destinations: Sequence[str], key: str
    ) -> Iterable[tuple[str, Mapping[str, object]]]:
        for destination in destinations:
            stats = self._destination_stats.get(self._normalize(destination))
            if not isinstance(stats, Mapping):
                continue
            for entry in self._extract_top_values(stats.get(key)):
                if isinstance(entry, Mapping):
                    yield destination, entry

    def _extract_top_values(self, section: object) -> List[Mapping[str, object]]:
        if isinstance(section, Mapping):
            values = section.get("top_values")
            if isinstance(values, Sequence):
                return [entry for entry in values if isinstance(entry, Mapping)]
        return []

    # ------------------------------------------------------------------
    # Index builders
    # ------------------------------------------------------------------
    def _build_destination_indexes(self, stats: object) -> None:
        destinations = self._fixtures.list_destinations()
        for entry in destinations:
            name = str(entry.get("name", "")).strip()
            identifier = str(entry.get("id", "")).strip()
            if not name or not identifier:
                continue
            normalized = self._normalize(name)
            self._destination_id_to_name[identifier] = name
            self._destination_candidates.setdefault(name, [normalized])

        if isinstance(stats, Mapping):
            for name, summary in stats.items():
                if not isinstance(summary, Mapping) or not isinstance(name, str):
                    continue
                key = self._normalize(name)
                self._destination_stats[key] = summary
                interval_section = summary.get("interval")
                total = 0
                if isinstance(interval_section, Mapping):
                    total = int(interval_section.get("total", 0) or 0)
                self._destination_frequency[key] = total

        synonyms = self._fixtures.locale_synonyms("destinations")
        for language_map in synonyms.values():
            for alias, target in language_map.items():
                alias_value = alias.strip().lower()
                canonical = self._destination_id_to_name.get(target)
                if not canonical or not alias_value:
                    continue
                bucket = self._destination_candidates.setdefault(canonical, [self._normalize(canonical)])
                if alias_value not in bucket:
                    bucket.append(alias_value)

        all_names = list({name for name in self._destination_candidates})
        self._destination_order = sorted(
            all_names,
            key=lambda name: (
                -self._destination_frequency.get(self._normalize(name), 0),
                name,
            ),
        )

    def _build_airport_indexes(self) -> None:
        airports = self._fixtures.list_airports()
        for entry in airports:
            name = str(entry.get("name", "")).strip()
            identifier = str(entry.get("id", "")).strip()
            if not name or not identifier:
                continue
            normalized = self._normalize(name)
            self._airport_id_to_name[identifier.upper()] = name
            bucket = self._airport_candidates.setdefault(name, [normalized])
            code = identifier.strip().lower()
            if code and code not in bucket:
                bucket.append(code)

        synonyms = self._fixtures.locale_synonyms("airports")
        for language_map in synonyms.values():
            for alias, target in language_map.items():
                canonical = self._airport_id_to_name.get(target)
                if not canonical:
                    continue
                alias_value = alias.strip().lower()
                bucket = self._airport_candidates.setdefault(canonical, [self._normalize(canonical)])
                if alias_value and alias_value not in bucket:
                    bucket.append(alias_value)

        global_section = self._global_stats.get("departure_airport")
        ordered = []
        if isinstance(global_section, Mapping):
            for entry in self._extract_top_values(global_section):
                value = entry.get("value") if isinstance(entry, Mapping) else None
                if isinstance(value, str) and value not in ordered:
                    ordered.append(value)
                    self._airport_frequency[value] = int(entry.get("count", 0) or 0)

        for name in self._airport_candidates:
            if name not in ordered:
                ordered.append(name)

        self._airport_order = ordered

    def _build_intersection_index(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            return
        for label, summary in payload.items():
            if not isinstance(summary, Mapping):
                continue
            destinations = summary.get("destinations")
            if isinstance(destinations, Sequence) and destinations:
                normalized = tuple(sorted({self._normalize(str(item)) for item in destinations if str(item).strip()}))
            else:
                normalized = tuple(sorted({self._normalize(part) for part in str(label).split("||") if part.strip()}))
            if not normalized:
                continue
            self._intersection_stats[normalized] = summary
            if isinstance(label, str) and label.strip():
                self._intersection_labels[normalized] = label
            else:
                self._intersection_labels[normalized] = "||".join(destinations) if destinations else "||".join(normalized)

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------
    def _load_statistics(self) -> Mapping[str, object] | None:
        if self._stats_path and self._stats_path.is_file():
            try:
                text = self._stats_path.read_text(encoding="utf-8")
            except OSError as exc:  # pragma: no cover - filesystem dependent
                logger.warning("Unable to read popularity statistics: %s", exc)
                return None
            return json.loads(text)
        if self._stats_path:
            logger.warning("Popularity statistics file '%s' not found", self._stats_path)
        return None

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().lower()


__all__ = ["AutoCompletionService"]
