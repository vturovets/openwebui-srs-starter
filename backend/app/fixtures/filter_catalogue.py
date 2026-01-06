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
        normalized = FiltersCatalogue.normalize_identifier(option_id)
        for option in self.options:
            if option.id == normalized:
                return option
        raise KeyError(f"Unknown option '{option_id}' for filter '{self.id}'")


class FiltersCatalogue:
    """Load and cache filters/options from ``filters_options.csv``."""

    REQUIRED_COLUMNS = ("filterId", "filterLabel", "optionId", "optionLabel")
    COLUMN_ALIASES = {
        "filterName": "filterLabel",
        "optionName": "optionLabel",
    }

    _NORMALIZE_PATTERN = re.compile(r"[^\w\s]+")
    _CODE_PATTERN = re.compile(r"^[A-Z0-9._+-]+$")

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
        self._filter_aliases: Dict[str, str] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        try:
            with self._path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=self._delimiter)
                resolved_columns = self._validate_columns(reader.fieldnames)
                reader.fieldnames = list(resolved_columns)
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
            filter_label = self._clean_label_field(entry, "filterLabel", "filterName")
            option_label_raw = self._clean_label_field(entry, "optionLabel", "optionName")

            synonyms_raw = entry.get("synonyms") or ""
            synonyms: Tuple[str, ...] = tuple(
                synonym.strip()
                for synonym in synonyms_raw.split("|")
                if synonym.strip()
            )

            normalized_filter_id = self.normalize_identifier(filter_label)
            normalized_option_id = self.normalize_identifier(option_id)
            option_label = self._resolve_option_label(option_id, option_label_raw)

            payload = {
                "filterId": normalized_filter_id,
                "filterLabel": filter_label,
                "optionId": normalized_option_id,
                "optionLabel": option_label,
                "synonyms": synonyms,
            }
            grouped.setdefault(normalized_filter_id, []).append(payload)
            alias_key = self.normalize_identifier(filter_id)
            if alias_key != normalized_filter_id:
                self._filter_aliases.setdefault(alias_key, normalized_filter_id)

        for filter_id, entries in grouped.items():
            filter_label = entries[0]["filterLabel"]
            options = self._build_options(entries)
            self._filters[filter_id] = FilterDefinition(
                id=filter_id,
                label=filter_label,
                normalized_label=self.normalize_label(filter_label),
                options=tuple(options),
            )

    def _resolve_columns(self, columns: Sequence[str]) -> List[str]:
        resolved = list(columns)
        for alias, canonical in self.COLUMN_ALIASES.items():
            if canonical not in resolved and alias in resolved:
                resolved = [canonical if column == alias else column for column in resolved]
        return resolved

    def _validate_columns(self, columns: Sequence[str] | None) -> List[str]:
        if not columns:
            raise ValueError("Filters catalogue is missing a header row")
        resolved = self._resolve_columns(columns)
        missing = [column for column in self.REQUIRED_COLUMNS if column not in resolved]
        if missing:
            raise ValueError(
                "Filters catalogue is missing required columns: " + ", ".join(missing)
            )
        return resolved

    def _clean_field(self, entry: Mapping[str, str], field: str) -> str:
        value = (entry.get(field) or "").strip()
        if not value:
            raise ValueError(f"Field '{field}' must not be empty in filters catalogue")
        return value

    def _clean_label_field(
        self, entry: Mapping[str, str], primary: str, fallback: str
    ) -> str:
        value = (entry.get(primary) or "").strip()
        if value:
            return value
        fallback_value = (entry.get(fallback) or "").strip()
        if fallback_value:
            return fallback_value
        raise ValueError(
            f"Fields '{primary}' and '{fallback}' must not be empty in filters catalogue"
        )

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

    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        """Normalize identifiers for filter/option keys."""

        normalized = cls.normalize_label(value)
        tokens = normalized.split()
        if not tokens:
            raise ValueError("Normalized identifier must not be empty")
        if len(tokens) == 1:
            return tokens[0]
        if any(len(token) > 2 for token in tokens):
            return "_".join(tokens)
        return "".join(tokens)

    def _looks_like_code(self, value: str) -> bool:
        return bool(self._CODE_PATTERN.fullmatch(value.strip()))

    def _resolve_option_label(self, option_id: str, option_label: str) -> str:
        label = option_label
        if self._looks_like_code(option_label):
            label = option_id
        label = label.strip()
        if label.endswith("*") and not label.lower().startswith("free "):
            label = f"Free {label.rstrip('*').strip()}"
        return label

    def list_filters(self) -> Tuple[FilterDefinition, ...]:
        return tuple(self._filters.values())

    def get_filter(self, filter_id: str) -> FilterDefinition:
        normalized = self.normalize_identifier(filter_id)
        canonical = self._filter_aliases.get(normalized, normalized)
        try:
            return self._filters[canonical]
        except KeyError as exc:
            raise KeyError(f"Unknown filter '{filter_id}'") from exc


__all__ = [
    "FilterDefinition",
    "FilterOption",
    "FiltersCatalogue",
]
