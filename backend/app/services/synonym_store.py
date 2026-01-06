"""Synonym ingestion and inverted index builder for rule-based mapping."""
from __future__ import annotations

from typing import Dict, Mapping, MutableMapping, Tuple

from ..fixtures.filter_catalogue import FilterOption, FiltersCatalogue


class SynonymStore:
    """Load canonical synonyms from the filters/options catalogue."""

    def __init__(self, catalogue: FiltersCatalogue) -> None:
        self._catalogue = catalogue
        self._synonyms: Dict[tuple[str, str], Tuple[str, ...]] = {}
        self._index: Dict[str, Tuple[tuple[str, str], ...]] = {}
        self._build_indexes()

    @property
    def inverted_index(self) -> Mapping[str, Tuple[tuple[str, str], ...]]:
        return dict(self._index)

    def synonyms_for(self, filter_id: str, option_id: str) -> Tuple[str, ...]:
        try:
            return self._synonyms[(filter_id, option_id)]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(f"No synonyms loaded for ({filter_id}, {option_id})") from exc

    def _build_indexes(self) -> None:
        synonym_map: Dict[tuple[str, str], Tuple[str, ...]] = {}
        inverted: MutableMapping[str, list[tuple[str, str]]] = {}

        for definition in self._catalogue.list_filters():
            for option in definition.options:
                normalized = self._normalize_synonyms(option)
                synonym_map[(definition.id, option.id)] = normalized
                for synonym in normalized:
                    inverted.setdefault(synonym, []).append((definition.id, option.id))

        self._synonyms = synonym_map
        self._index = {key: tuple(values) for key, values in inverted.items()}

    def _normalize_synonyms(self, option: FilterOption) -> Tuple[str, ...]:
        normalized = {option.normalized_label}
        normalized.update(option.normalized_synonyms)

        return tuple(sorted(normalized))


__all__ = ["SynonymStore"]
