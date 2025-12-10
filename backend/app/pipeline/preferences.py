from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Mapping

from .configuration import MethodConfig, MethodsCatalog
from .language import LanguageDetectionResult, LanguageDetector
from ..config import Settings


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
        timings: dict[str, float] = {}
        total_start = perf_counter()

        detection = self._measure(
            "languageMs",
            timings,
            lambda: self._language.detect(utterance),
        )

        requested_alias, resolved_method = self._resolve_method(method)

        total_ms = (perf_counter() - total_start) * 1000
        timings["totalMs"] = total_ms

        metadata: dict[str, object] = {
            "methodId": resolved_method.id,
            "methodType": resolved_method.kind,
            "availableMethods": self._methods_catalog.to_metadata(),
            "methodDefaults": dict(self._methods_catalog.defaults),
            "defaultMethod": self._methods_catalog.default_method_id,
            "catalogSize": len(self._methods_catalog.list_methods()),
        }
        if requested_alias and requested_alias.lower() != resolved_method.id.lower():
            metadata["requestedAlias"] = requested_alias

        return PreferenceRunResult(
            status="no-preferences-detected",
            method_requested=resolved_method.id,
            method_used=resolved_method.id,
            detection=detection,
            filters=[],
            timings=timings,
            metadata=metadata,
            mappings=[],
            error=None,
        )


__all__ = [
    "PreferencesPipeline",
    "PreferenceRunResult",
]
