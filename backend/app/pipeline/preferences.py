from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Mapping

from .configuration import MethodConfig, MethodsCatalog
from .language import LanguageDetectionResult, LanguageDetector
from .preferences_mapping import (
    HybridPreferenceMapper,
    LLMPreferenceMapper,
    PreferenceMappingStrategy,
    RulesPreferenceMapper,
)
from ..config import Settings
from ..fixtures.filter_catalogue import FiltersCatalogue


@dataclass
class PreferenceRunResult:
    """Aggregate result from running the preferences interpreter."""

    status: str
    method_requested: str | None
    method_used: str
    detection: LanguageDetectionResult
    filters: list[Mapping[str, object]]
    timings: dict[str, float]
    metadata: dict[str, object]
    mappings: list[Mapping[str, object]] | None = None
    error: str | None = None


class PreferencesPipeline:
    """Lightweight pipeline for interpreting free-text preferences."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        methods_catalog: MethodsCatalog | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._language = LanguageDetector(self._settings.allowed_langs)
        self._methods_catalog = methods_catalog or self._settings.load_methods_catalog()
        self._filters_catalogue = FiltersCatalogue(
            self._settings.resolve_filters_options_path(),
            delimiter=self._settings.filters_options_delimiter,
        )
        self._strategies: dict[str, PreferenceMappingStrategy] = {
            "rules": RulesPreferenceMapper(self._filters_catalogue),
            "llm": LLMPreferenceMapper(self._filters_catalogue),
            "hybrid": HybridPreferenceMapper(self._filters_catalogue),
        }

    def _resolve_method(self, override: str | None) -> tuple[str | None, MethodConfig]:
        candidate = override or self._settings.llm_method
        alias = candidate.strip() if isinstance(candidate, str) else None
        if alias:
            method = self._methods_catalog.lookup(alias)
            if method is not None:
                return alias, method
        return alias, self._methods_catalog.default_method

    def _measure(self, label: str, timings: dict[str, float], func):
        start = perf_counter()
        try:
            return func()
        finally:
            timings[label] = timings.get(label, 0.0) + (perf_counter() - start) * 1000

    def run(self, utterance: str, *, method: str | None = None) -> PreferenceRunResult:
        if not isinstance(utterance, str) or not utterance.strip():
            raise ValueError("Utterance must be a non-empty string for preference mapping")
        timings: dict[str, float] = {}
        total_start = perf_counter()

        detection = self._measure(
            "languageMs",
            timings,
            lambda: self._language.detect(utterance),
        )

        requested_alias, resolved_method = self._resolve_method(method)

        status: str
        filter_payload: list[Mapping[str, object]]
        mappings: list[Mapping[str, object]] | None
        strategy = self._strategies.get(resolved_method.kind, RulesPreferenceMapper(self._filters_catalogue))
        status, selections, mapping_payload = self._measure(
            "mappingMs",
            timings,
            lambda: strategy.map(utterance, language=detection.language),
        )

        filter_payload = [selection.to_payload() for selection in selections]
        mappings = mapping_payload

        total_ms = (perf_counter() - total_start) * 1000
        timings["totalMs"] = total_ms

        metadata: dict[str, object] = {
            "methodId": resolved_method.id,
            "methodType": resolved_method.kind,
            "method": resolved_method.id,
            "availableMethods": self._methods_catalog.to_metadata(),
            "methodDefaults": dict(self._methods_catalog.defaults),
            "defaultMethod": self._methods_catalog.default_method_id,
            "catalogSize": len(self._methods_catalog.list_methods()),
        }
        if requested_alias and requested_alias.lower() != resolved_method.id.lower():
            metadata["requestedAlias"] = requested_alias

        return PreferenceRunResult(
            status=status,
            method_requested=resolved_method.id,
            method_used=resolved_method.id,
            detection=detection,
            filters=filter_payload,
            timings=timings,
            metadata=metadata,
            mappings=mappings,
            error=None,
        )


__all__ = [
    "PreferencesPipeline",
    "PreferenceRunResult",
]
