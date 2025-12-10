"""Filters and options catalogue loader for preference mapping."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class FilterOption:
    """Single option belonging to a filter in the catalogue."""

    id: str
    label: str
    normalized_label: str
    synonyms: Tuple[str, ...] = ()
    normalized_synonyms: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FilterDefinition:
    """Filter with a collection of available options."""

    id: str
    label: str
    normalized_label: str
    options: Tuple[FilterOption, ...]

    def get_option(self, option_id: str) -> FilterOption:
        for option in self.options:
            if option.id.lower() == option_id.lower():
                return option
        raise KeyError(f"Unknown option '{option_id}' for filter '{self.id}'")


class FiltersCatalogue:
    """Load and cache filters/options from ``filters_options.csv``."""

    REQUIRED_COLUMNS = ("filterId", "filterLabel", "optionId", "optionLabel")

    _NORMALIZE_PATTERN = re.compile(r"[^\w\s]+")

    def __init__(self, path: str | Path, *, delimiter: str = ",") -> None:
        self._path = Path(path)
        if len(delimiter) != 1:
            raise ValueError("CSV delimiter must be a single character")
        self._delimiter = delimiter

        if not self._path.is_file():
            raise FileNotFoundError(
                f"Filters catalogue '{self._path}' does not exist or is not readable"
            )

        self._filters: Dict[str, FilterDefinition] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        try:
            with self._path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=self._delimiter)
                self._validate_columns(reader.fieldnames)
                rows = list(reader)
        except OSError as exc:  # pragma: no cover - filesystem errors
            raise FileNotFoundError(
                f"Unable to read filters catalogue '{self._path}': {exc}"
            ) from exc
        except csv.Error as exc:
            raise ValueError(f"Invalid CSV in filters catalogue: {exc}") from exc

        if not rows:
            raise ValueError("Filters catalogue is empty")

        grouped: Dict[str, List[Mapping[str, str]]] = {}
        for entry in rows:
            filter_id = self._clean_field(entry, "filterId")
            option_id = self._clean_field(entry, "optionId")
            filter_label = self._clean_field(entry, "filterLabel")
            option_label = self._clean_field(entry, "optionLabel")

            synonyms_raw = entry.get("synonyms") or ""
            synonyms: Tuple[str, ...] = tuple(
                synonym.strip()
                for synonym in synonyms_raw.split("|")
                if synonym.strip()
            )

            payload = {
                "filterId": filter_id,
                "filterLabel": filter_label,
                "optionId": option_id,
                "optionLabel": option_label,
                "synonyms": synonyms,
            }
            grouped.setdefault(filter_id, []).append(payload)

        for filter_id, entries in grouped.items():
            filter_label = entries[0]["filterLabel"]
            options = self._build_options(entries)
            self._filters[filter_id] = FilterDefinition(
                id=filter_id,
                label=filter_label,
                normalized_label=self.normalize_label(filter_label),
                options=tuple(options),
            )

    def _validate_columns(self, columns: Sequence[str] | None) -> None:
        if not columns:
            raise ValueError("Filters catalogue is missing a header row")
        missing = [column for column in self.REQUIRED_COLUMNS if column not in columns]
        if missing:
            raise ValueError(
                "Filters catalogue is missing required columns: " + ", ".join(missing)
            )

    def _clean_field(self, entry: Mapping[str, str], field: str) -> str:
        value = (entry.get(field) or "").strip()
        if not value:
            raise ValueError(f"Field '{field}' must not be empty in filters catalogue")
        return value

    def _build_options(self, entries: Iterable[Mapping[str, object]]) -> List[FilterOption]:
        options: List[FilterOption] = []
        seen: set[str] = set()
        for entry in entries:
            option_id = str(entry["optionId"]).strip()
            if option_id.lower() in seen:
                raise ValueError(
                    f"Duplicate option identifier '{option_id}' detected for filter '{entry['filterId']}'"
                )
            seen.add(option_id.lower())
            option_label = str(entry["optionLabel"])
            synonyms = tuple(entry.get("synonyms", ()) or ())
            normalized_synonyms = tuple(
                self.normalize_label(synonym) for synonym in synonyms if synonym
            )
            options.append(
                FilterOption(
                    id=option_id,
                    label=option_label,
                    normalized_label=self.normalize_label(option_label),
                    synonyms=synonyms,
                    normalized_synonyms=normalized_synonyms,
                )
            )
        return options

    @classmethod
    def normalize_label(cls, label: str) -> str:
        """Normalize labels and synonyms for consistent matching."""

        normalized = cls._NORMALIZE_PATTERN.sub(" ", label.lower())
        normalized = " ".join(normalized.split())
        if not normalized:
            raise ValueError("Normalized label must not be empty")
        return normalized

    def list_filters(self) -> Tuple[FilterDefinition, ...]:
        return tuple(self._filters.values())

    def get_filter(self, filter_id: str) -> FilterDefinition:
        try:
            return self._filters[filter_id]
        except KeyError as exc:
            raise KeyError(f"Unknown filter '{filter_id}'") from exc


__all__ = [
    "FilterDefinition",
    "FilterOption",
    "FiltersCatalogue",
]
