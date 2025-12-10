"""Mapping strategies for transforming text into filter selections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Tuple

from ..fixtures.filter_catalogue import FilterDefinition, FilterOption, FiltersCatalogue


@dataclass(frozen=True)
class FilterOptionSelection:
    """Selected option tied to the catalogue definition."""

    id: str
    label: str
    selected: bool = True
    confidence: float | None = None

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "optionId": self.id,
            "optionLabel": self.label,
            "selected": self.selected,
        }
        if self.confidence is not None:
            payload["confidence"] = float(self.confidence)
        return payload


@dataclass(frozen=True)
class FilterSelection:
    """Filter plus constrained option selections."""

    filter_id: str
    filter_label: str
    options: Tuple[FilterOptionSelection, ...]

    @classmethod
    def from_catalogue(
        cls,
        definition: FilterDefinition,
        options: Iterable[FilterOption | FilterOptionSelection],
        *,
        selected: bool = True,
        confidence: float | None = None,
    ) -> "FilterSelection":
        selections: List[FilterOptionSelection] = []
        available = {option.id.lower() for option in definition.options}
        for option in options:
            if isinstance(option, FilterOptionSelection):
                option_id = option.id
                if option_id.lower() not in available:
                    raise ValueError(
                        f"Option '{option_id}' is not part of filter '{definition.id}'"
                    )
                selections.append(option)
                continue

            if option.id.lower() not in available:
                raise ValueError(
                    f"Option '{option.id}' is not part of filter '{definition.id}'"
                )
            selections.append(
                FilterOptionSelection(
                    id=option.id,
                    label=option.label,
                    selected=selected,
                    confidence=confidence,
                )
            )
        return cls(
            filter_id=definition.id,
            filter_label=definition.label,
            options=tuple(selections),
        )

    def to_payload(self) -> Dict[str, object]:
        return {
            "filterId": self.filter_id,
            "filterLabel": self.filter_label,
            "options": [option.to_payload() for option in self.options],
        }


class PreferenceMappingStrategy:
    """Base mapping strategy using catalogue-backed options only."""

    def __init__(self, catalogue: FiltersCatalogue) -> None:
        self._catalogue = catalogue

    def map(self, utterance: str, *, language: str) -> Tuple[str, List[FilterSelection], List[Mapping[str, object]]]:
        raise NotImplementedError

    def _match_synonyms(
        self,
        utterance: str,
        option: FilterOption,
        extra_synonyms: Iterable[str] | None = None,
    ) -> bool:
        synonyms = list(option.synonyms)
        if extra_synonyms:
            synonyms.extend(extra_synonyms)
        lowered = utterance.lower()
        for synonym in synonyms:
            pattern = r"\b" + re.escape(synonym) + r"\b"
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                return True
        return False


class RulesPreferenceMapper(PreferenceMappingStrategy):
    """Lightweight heuristic mapper for baseline coverage."""

    NEGATIVE_HINTS = ("no catering", "without catering", "no meals")

    def map(
        self, utterance: str, *, language: str
    ) -> Tuple[str, List[FilterSelection], List[Mapping[str, object]]]:
        selections: Dict[str, List[FilterOption]] = {}
        mappings: List[Mapping[str, object]] = []

        for definition in self._catalogue.list_filters():
            for option in definition.options:
                if self._match_synonyms(utterance, option):
                    selections.setdefault(definition.id, []).append(option)
                    mappings.append(
                        {
                            "filterId": definition.id,
                            "optionId": option.id,
                            "spans": [{"text": option.label}],
                        }
                    )

        lowered = utterance.lower()
        for hint in self.NEGATIVE_HINTS:
            if hint in lowered:
                try:
                    boards = self._catalogue.get_filter("boards")
                    room_only = boards.get_option("room_only")
                except KeyError:
                    break
                selections.setdefault(boards.id, []).append(room_only)
                mappings.append(
                    {
                        "filterId": boards.id,
                        "optionId": room_only.id,
                        "spans": [{"text": hint}],
                    }
                )
                break

        filter_selections: List[FilterSelection] = []
        for filter_id, options in selections.items():
            definition = self._catalogue.get_filter(filter_id)
            filter_selections.append(
                FilterSelection.from_catalogue(definition, options, confidence=0.9)
            )

        status = "success" if filter_selections else "no-preferences-detected"
        return status, filter_selections, mappings


class LLMPreferenceMapper(RulesPreferenceMapper):
    """Placeholder LLM mapper that reuses heuristic signals for now."""

    def map(
        self, utterance: str, *, language: str
    ) -> Tuple[str, List[FilterSelection], List[Mapping[str, object]]]:
        # In this starter implementation, mirror the rules strategy while
        # preserving the contract for catalogue-backed options.
        return super().map(utterance, language=language)


class HybridPreferenceMapper(RulesPreferenceMapper):
    """Cascade mapper to mirror hybrid method semantics."""

    def map(
        self, utterance: str, *, language: str
    ) -> Tuple[str, List[FilterSelection], List[Mapping[str, object]]]:
        status, selections, mappings = super().map(utterance, language=language)
        return status, selections, mappings


__all__ = [
    "FilterSelection",
    "FilterOptionSelection",
    "HybridPreferenceMapper",
    "LLMPreferenceMapper",
    "PreferenceMappingStrategy",
    "RulesPreferenceMapper",
]
