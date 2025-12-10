"""Mapping strategies for transforming text into filter selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Tuple

from ..fixtures.filter_catalogue import FilterDefinition, FilterOption, FiltersCatalogue
from ..services.text_processing import NegationHandler, TextPreprocessor


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


class RulesPreferenceMapper(PreferenceMappingStrategy):
    """Lightweight heuristic mapper for baseline coverage."""

    def __init__(self, catalogue: FiltersCatalogue) -> None:
        super().__init__(catalogue)
        self._preprocessor = TextPreprocessor(normalizer=self._catalogue.normalize_label)
        self._negation = NegationHandler()

    def map(
        self, utterance: str, *, language: str
    ) -> Tuple[str, List[FilterSelection], List[Mapping[str, object]]]:
        selections: Dict[str, List[FilterOption]] = {}
        mappings: List[Mapping[str, object]] = []

        negation_cleaned, _negation_spans = self._negation.apply(
            utterance, normalizer=self._catalogue.normalize_label
        )
        processed = self._preprocessor.preprocess(negation_cleaned)
        ngram_set = set(processed.ngrams)

        for definition in self._catalogue.list_filters():
            for option in definition.options:
                normalized_synonyms = {option.normalized_label, *option.normalized_synonyms}
                if self._match_synonyms(ngram_set, normalized_synonyms):
                    selections.setdefault(definition.id, []).append(option)
                    mappings.append(
                        {
                            "filterId": definition.id,
                            "optionId": option.id,
                            "spans": [
                                {
                                    "text": option.label,
                                    "normalized": next(iter(normalized_synonyms)),
                                }
                            ],
                        }
                    )

        filter_selections: List[FilterSelection] = []
        for filter_id, options in selections.items():
            definition = self._catalogue.get_filter(filter_id)
            filter_selections.append(
                FilterSelection.from_catalogue(definition, options, confidence=0.9)
            )

        status = "success" if filter_selections else "no-preferences-detected"
        return status, filter_selections, mappings

    def _match_synonyms(
        self, normalized_ngrams: set[str], normalized_synonyms: Iterable[str]
    ) -> bool:
        for synonym in normalized_synonyms:
            if synonym in normalized_ngrams:
                return True
        return False


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
