"""Mapping strategies for transforming text into filter selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, MutableMapping, Tuple

from ..fixtures.filter_catalogue import FilterDefinition, FilterOption, FiltersCatalogue
from ..services.text_processing import NegationHandler, TextPreprocessor
from ..services.synonym_store import SynonymStore


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

    def __init__(
        self,
        catalogue: FiltersCatalogue,
        *,
        synonym_store: SynonymStore | None = None,
        threshold: float = 0.6,
        negation_penalty: float = 0.25,
    ) -> None:
        super().__init__(catalogue)
        self._preprocessor = TextPreprocessor(normalizer=self._catalogue.normalize_label)
        self._negation = NegationHandler()
        self._synonyms = synonym_store or SynonymStore(self._catalogue)
        self._threshold = max(0.0, min(1.0, threshold))
        self._negation_penalty = max(0.0, negation_penalty)

    def map(
        self, utterance: str, *, language: str
    ) -> Tuple[str, List[FilterSelection], List[Mapping[str, object]]]:
        candidate_scores: MutableMapping[tuple[str, str], dict[str, object]] = {}
        mappings: List[Mapping[str, object]] = []

        negation_cleaned, negation_spans = self._negation.apply(
            utterance, normalizer=self._catalogue.normalize_label
        )
        processed = self._preprocessor.preprocess(negation_cleaned)
        negation_replacements = {
            self._catalogue.normalize_label(span.replacement)
            for span in negation_spans
            if span.replacement
        }
        negated_phrases = {
            self._catalogue.normalize_label(span.phrase)
            for span in negation_spans
            if not span.replacement
        }

        for ngram in processed.ngrams:
            targets = self._synonyms.inverted_index.get(ngram, ())
            if not targets:
                continue

            is_blocked = ngram in negated_phrases
            negated_hit = ngram in negation_replacements
            for filter_id, option_id in targets:
                key = (filter_id, option_id)
                stats = candidate_scores.setdefault(
                    key,
                    {
                        "phrases": [],
                        "hits": 0,
                        "length_sum": 0,
                        "negated_hits": 0,
                        "blocked": False,
                    },
                )
                stats["phrases"].append(ngram)
                stats["hits"] += 1
                stats["length_sum"] += len(ngram.split())
                if negated_hit:
                    stats["negated_hits"] += 1
                if is_blocked:
                    stats["blocked"] = True

        filter_selections: Dict[str, List[FilterOptionSelection]] = {}

        for (filter_id, option_id), stats in candidate_scores.items():
            definition = self._catalogue.get_filter(filter_id)
            option = definition.get_option(option_id)
            confidence = self._score_candidate(stats)
            selected = confidence >= self._threshold and not stats.get("blocked")
            selection = FilterOptionSelection(
                id=option.id,
                label=option.label,
                selected=selected,
                confidence=confidence,
            )
            filter_selections.setdefault(filter_id, []).append(selection)
            mappings.append(
                {
                    "filterId": filter_id,
                    "optionId": option_id,
                    "spans": [
                        {"text": phrase, "normalized": phrase}
                        for phrase in sorted(set(stats["phrases"]))
                    ],
                    "confidence": confidence,
                    "hits": stats["hits"],
                    "blocked": bool(stats.get("blocked")),
                }
            )

        compiled: List[FilterSelection] = []
        for filter_id, options in filter_selections.items():
            definition = self._catalogue.get_filter(filter_id)
            compiled.append(FilterSelection.from_catalogue(definition, options))

        status = "success" if compiled else "no-preferences-detected"
        return status, compiled, mappings

    def _score_candidate(self, stats: Mapping[str, object]) -> float:
        hits = int(stats.get("hits", 0))
        if hits <= 0:
            return 0.0

        length_sum = int(stats.get("length_sum", 0))
        avg_length = length_sum / hits if hits else 0.0
        length_bonus = min(avg_length / 3.0, 1.0)
        frequency_bonus = min(hits / 2.0, 1.0)
        penalty = self._negation_penalty * int(stats.get("negated_hits", 0))

        confidence = 0.35 + 0.4 * length_bonus + 0.25 * frequency_bonus - penalty
        return max(0.0, min(1.0, confidence))


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
