"""Synonym ingestion and inverted index builder for rule-based mapping."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Mapping, MutableMapping, Tuple

import yaml

from ..fixtures.filter_catalogue import FilterOption, FiltersCatalogue


class SynonymStore:
    """Load canonical synonyms and provide an inverted index for lookups."""

    def __init__(self, catalogue: FiltersCatalogue, path: str | Path) -> None:
        self._catalogue = catalogue
        self._path = Path(path)
        self._synonyms: Dict[tuple[str, str], Tuple[str, ...]] = {}
        self._index: Dict[str, Tuple[tuple[str, str], ...]] = {}
        self.reload()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def inverted_index(self) -> Mapping[str, Tuple[tuple[str, str], ...]]:
        return dict(self._index)

    def synonyms_for(self, filter_id: str, option_id: str) -> Tuple[str, ...]:
        try:
            return self._synonyms[(filter_id, option_id)]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(f"No synonyms loaded for ({filter_id}, {option_id})") from exc

    def reload(self) -> None:
        """Reload the synonym file and rebuild the inverted index."""

        if not self._path.is_file():
            raise FileNotFoundError(f"Synonym file '{self._path}' does not exist")

        data = self._load_file(self._path)
        self._validate_schema(data)
        self._build_indexes(data)

    def _load_file(self, path: Path) -> Mapping[str, object]:
        if path.suffix.lower() in {".yaml", ".yml"}:
            loader = yaml.safe_load
        else:
            loader = json.load

        with path.open(encoding="utf-8") as handle:
            payload = loader(handle)
        if payload is None:
            raise ValueError("Synonym file is empty")
        if not isinstance(payload, Mapping):
            raise ValueError("Synonym file must contain a mapping of filterIds")
        return payload

    def _validate_schema(self, payload: Mapping[str, object]) -> None:
        for filter_id, options in payload.items():
            if not isinstance(options, Mapping):
                raise ValueError("Synonym entries must map filterIds to option mappings")
            try:
                definition = self._catalogue.get_filter(str(filter_id))
            except KeyError as exc:
                raise ValueError(f"Unknown filter in synonym file: {filter_id}") from exc

            for option_id, synonyms in options.items():
                try:
                    definition.get_option(str(option_id))
                except KeyError as exc:
                    raise ValueError(
                        f"Unknown option '{option_id}' for filter '{filter_id}' in synonym file"
                    ) from exc
                if not isinstance(synonyms, Iterable) or isinstance(synonyms, (str, bytes)):
                    raise ValueError("Synonym lists must be iterable collections of strings")
                for synonym in synonyms:
                    if not isinstance(synonym, str) or not synonym.strip():
                        raise ValueError("Synonyms must be non-empty strings")

    def _build_indexes(self, payload: Mapping[str, object]) -> None:
        synonym_map: Dict[tuple[str, str], Tuple[str, ...]] = {}
        inverted: MutableMapping[str, list[tuple[str, str]]] = {}

        for filter_id, options in payload.items():
            definition = self._catalogue.get_filter(str(filter_id))
            for option_id, synonyms in options.items():
                option = definition.get_option(str(option_id))
                normalized = self._normalize_synonyms(option, synonyms)
                synonym_map[(definition.id, option.id)] = normalized
                for synonym in normalized:
                    inverted.setdefault(synonym, []).append((definition.id, option.id))

        self._synonyms = synonym_map
        self._index = {key: tuple(values) for key, values in inverted.items()}

    def _normalize_synonyms(
        self,
        option: FilterOption,
        synonyms: Iterable[str],
    ) -> Tuple[str, ...]:
        normalized = {option.normalized_label}
        normalized.update(option.normalized_synonyms)

        for synonym in synonyms:
            normalized.add(self._catalogue.normalize_label(synonym))

        return tuple(sorted(normalized))


__all__ = ["SynonymStore"]
