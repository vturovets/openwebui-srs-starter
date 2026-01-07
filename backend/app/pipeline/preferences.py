from __future__ import annotations

from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Mapping

from .configuration import MethodConfig, MethodsCatalog
from .language import LanguageDetectionResult, LanguageDetector
from .preferences_mapping import (
    HybridPreferenceMapper,
    LLMPreferenceMapper,
    PreferenceMappingStrategy,
    RulesPreferenceMapper,
    SemanticPreferenceMapper,
)
from ..config import Settings
from ..fixtures.filter_catalogue import FiltersCatalogue
from ..services.synonym_store import SynonymStore

logger = logging.getLogger(__name__)


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
        self._language = LanguageDetector(
            self._settings.preferences_rules_langs or self._settings.allowed_langs
        )
        self._methods_catalog = methods_catalog or self._settings.load_methods_catalog()
        self._filters_catalogue: FiltersCatalogue | None = None
        self._synonym_store: SynonymStore | None = None
        self._strategies: dict[str, PreferenceMappingStrategy] = {}

    def _build_strategies(
        self,
        catalogue: FiltersCatalogue,
        synonym_store: SynonymStore,
    ) -> dict[str, PreferenceMappingStrategy]:
        threshold = self._settings.preferences_rules_threshold
        negation_penalty = self._settings.preferences_rules_negation_penalty
        semantic_method = self._methods_catalog.lookup("semantic")
        semantic_params = (
            dict(semantic_method.params) if semantic_method is not None else {}
        )

        def coerce_float(value: object, fallback: float) -> float:
            if value is None:
                return fallback
            try:
                return float(value)
            except (TypeError, ValueError):
                return fallback

        def coerce_int(value: object, fallback: int) -> int:
            if value is None:
                return fallback
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        model_name = semantic_params.get("model_name")
        if model_name is None:
            model_name = self._settings.pref_embed_model_name
        else:
            model_name = str(model_name).strip() or self._settings.pref_embed_model_name

        similarity_threshold = coerce_float(
            semantic_params.get("similarity_threshold"),
            self._settings.pref_embed_similarity_threshold,
        )
        top_k = coerce_int(
            semantic_params.get("top_k"),
            self._settings.pref_embed_top_k,
        )
        return {
            "rules": RulesPreferenceMapper(
                catalogue,
                synonym_store=synonym_store,
                threshold=threshold,
                negation_penalty=negation_penalty,
            ),
            "llm": LLMPreferenceMapper(
                catalogue,
                synonym_store=synonym_store,
                threshold=threshold,
                negation_penalty=negation_penalty,
            ),
            "hybrid": HybridPreferenceMapper(
                catalogue,
                synonym_store=synonym_store,
                threshold=threshold,
                negation_penalty=negation_penalty,
            ),
            "semantic": SemanticPreferenceMapper(
                catalogue,
                synonym_store=synonym_store,
                model_name=model_name,
                similarity_threshold=similarity_threshold,
                top_k=top_k,
                negation_penalty=negation_penalty,
            ),
        }

    def _ensure_catalogue_loaded(self) -> None:
        if self._filters_catalogue is None:
            catalogue = FiltersCatalogue(
                self._settings.resolve_filters_options_path(),
                delimiter=self._settings.filters_options_delimiter,
            )
            synonym_store = SynonymStore(catalogue)
            self._filters_catalogue = catalogue
            self._synonym_store = synonym_store
            if not self._strategies:
                self._strategies = self._build_strategies(catalogue, synonym_store)
            return

        if self._synonym_store is None:
            self._synonym_store = SynonymStore(self._filters_catalogue)

        if not self._strategies and self._synonym_store is not None:
            self._strategies = self._build_strategies(
                self._filters_catalogue, self._synonym_store
            )

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
        error: str | None = None
        try:
            self._ensure_catalogue_loaded()
        except Exception as exc:
            logger.exception("Failed to load preference catalogue")
            status = "invalid-catalogue"
            selections = []
            mapping_payload = []
            error = str(exc)
        else:
            strategy = self._strategies.get(resolved_method.kind)
            if strategy is None and self._filters_catalogue is not None:
                strategy = RulesPreferenceMapper(self._filters_catalogue)

            try:
                if strategy is None:
                    raise ValueError("Preference mapping strategy is unavailable")

                status, selections, mapping_payload = self._measure(
                    "mappingMs",
                    timings,
                    lambda: strategy.map(utterance, language=detection.language),
                )
                if resolved_method.kind == "semantic":
                    options_count = sum(
                        len(selection.options) for selection in selections
                    )
                    logger.info(
                        "Semantic mapping completed in %.2fms with %d options",
                        timings.get("mappingMs", 0.0),
                        options_count,
                    )
            except Exception as exc:
                logger.exception("Preference mapping failed")
                status = "invalid-catalogue"
                selections = []
                mapping_payload = []
                error = str(exc)

        filter_payload = [selection.to_payload() for selection in selections]
        mappings = mapping_payload

        total_ms = (perf_counter() - total_start) * 1000
        timings["totalMs"] = total_ms
        threshold_ms = self._settings.processing_threshold_ms
        timings["thresholdBreached"] = total_ms > threshold_ms

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
        requested_method = requested_alias or resolved_method.id

        return PreferenceRunResult(
            status=status,
            method_requested=requested_method,
            method_used=resolved_method.id,
            detection=detection,
            filters=filter_payload,
            timings=timings,
            metadata=metadata,
            mappings=mappings,
            error=error,
        )


__all__ = [
    "PreferencesPipeline",
    "PreferenceRunResult",
]
