"""Pipeline orchestration and configuration helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Dict, Mapping

from ..config import Settings
from ..fixtures.repository import FixtureRepository
from .configuration import SearchConfiguration
from .extractor_rules import ExtractionResult, RulesExtractor
from .extractors import ExtractorOutcome, HybridExtractor, LLMExtractor
from .language import LanguageDetector, LanguageDetectionResult
from .normalizer import Normalizer, NormalizedResult
from .validator import ValidationError, Validator


@dataclass
class PipelineRunResult:
    """Aggregate result from running the pipeline."""

    status: str
    method_requested: str
    method_used: str
    detection: LanguageDetectionResult
    extraction: ExtractionResult | None
    normalized: NormalizedResult | None
    validation: Dict[str, Any]
    metadata: Dict[str, Any]
    attempts: list[Dict[str, Any]]
    timings: Dict[str, float]
    error: str | None = None


class HolidaySearchPipeline:
    """Co-ordinate language detection, extraction, normalisation, and validation."""

    CONFIG_FILENAME = "configuration_search.json"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        fixtures_dir: str | Path | None = None,
        llm_client: Callable[[str], Mapping[str, object]] | None = None,
    ) -> None:
        self._settings = settings or Settings()
        fixtures_root = Path(fixtures_dir or self._settings.fixtures_dir)
        self._fixtures = FixtureRepository(fixtures_root)
        self._configuration = self._load_search_configuration(fixtures_root)

        self._language = LanguageDetector(self._settings.allowed_langs)
        self._rules_extractor = RulesExtractor(self._fixtures, self._configuration)
        self._normalizer = Normalizer(
            self._configuration,
            available_checkin_dates=self._fixtures.list_checkin_dates(),
        )
        self._validator = Validator(self._fixtures, self._configuration)
        self._llm_extractor = LLMExtractor(
            self._fixtures,
            self._configuration,
            llm_client=llm_client,
        )
        self._hybrid_extractor = HybridExtractor(self._rules_extractor, self._llm_extractor)

    def _load_search_configuration(self, fixtures_root: Path) -> SearchConfiguration:
        config_path = fixtures_root / self.CONFIG_FILENAME
        if not config_path.is_file():
            raise FileNotFoundError(f"Search configuration file '{config_path}' not found")
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Configuration fixture must be a JSON object")
        return SearchConfiguration.from_fixture_payload(payload)

    def _measure(self, label: str, timings: Dict[str, float], func):
        start = perf_counter()
        try:
            return func()
        finally:
            timings[label] = timings.get(label, 0.0) + (perf_counter() - start) * 1000

    def _run_single_pass(
        self,
        method: str,
        utterance: str,
        language: str,
        timings: Dict[str, float],
    ) -> ExtractorOutcome:
        metadata_payload: Dict[str, Any] = {}
        try:
            extraction = self._measure(
                "extractionMs",
                timings,
                (lambda: self._rules_extractor.extract(utterance, language=language))
                if method == "rules"
                else (lambda: self._llm_extractor.extract(utterance)),
            )
        except ValueError as exc:
            detail = str(exc)
            validation = {
                "status": "error",
                "errors": [{"message": detail}],
            }
            return ExtractorOutcome(
                method=method,
                status="error",
                extraction=None,
                normalized=None,
                validation=validation,
                detail=detail,
                attempts=[{"method": method, "status": "error", "detail": detail}],
                metadata=metadata_payload,
            )

        if method == "llm":
            network_ms = self._llm_extractor.last_network_latency_ms
            if network_ms is not None:
                timings["llmNetworkMs"] = timings.get("llmNetworkMs", 0.0) + network_ms
            llm_metadata = self._llm_extractor.last_metadata
            if isinstance(llm_metadata, Mapping):
                metadata_payload["llm"] = dict(llm_metadata)

        normalized = self._measure(
            "normalizationMs",
            timings,
            lambda: self._normalizer.normalize(language, extraction),
        )

        try:
            self._measure(
                "validationMs",
                timings,
                lambda: self._validator.validate(normalized),
            )
        except ValidationError as exc:
            detail = str(exc)
            validation = {
                "status": "failed",
                "errors": [{"message": detail}],
            }
            return ExtractorOutcome(
                method=method,
                status="failed",
                extraction=extraction,
                normalized=normalized,
                validation=validation,
                detail=detail,
                attempts=[{"method": method, "status": "failed", "detail": detail}],
                metadata=metadata_payload,
            )

        validation = {"status": "passed", "errors": []}
        return ExtractorOutcome(
            method=method,
            status="success",
            extraction=extraction,
            normalized=normalized,
            validation=validation,
            attempts=[{"method": method, "status": "success"}],
            metadata=metadata_payload,
        )

    def _resolve_method(self, override: str | None) -> tuple[str, str]:
        preferred = override or self._settings.llm_method or "rules"
        requested = preferred.strip() or "rules"
        normalised = requested.lower()
        if normalised not in {"rules", "llm", "hybrid"}:
            return requested, "rules"
        return requested, normalised

    def run(self, utterance: str, *, method: str | None = None) -> PipelineRunResult:
        timings: Dict[str, float] = {}
        total_start = perf_counter()

        detection = self._measure(
            "languageMs",
            timings,
            lambda: self._language.detect(utterance),
        )

        requested, resolved = self._resolve_method(method)

        if resolved == "hybrid":
            outcome = self._hybrid_extractor.run(
                run_rules=lambda: self._run_single_pass("rules", utterance, detection.language, timings),
                run_llm=lambda: self._run_single_pass("llm", utterance, detection.language, timings),
            )
        else:
            outcome = self._run_single_pass(resolved, utterance, detection.language, timings)

        total_ms = (perf_counter() - total_start) * 1000
        timings["totalMs"] = total_ms

        metadata = dict(outcome.metadata)
        attempts = list(outcome.attempts)

        normalized = outcome.normalized
        if not isinstance(normalized, NormalizedResult):
            normalized = None

        return PipelineRunResult(
            status=outcome.status,
            method_requested=requested,
            method_used=outcome.method,
            detection=detection,
            extraction=outcome.extraction,
            normalized=normalized,
            validation=dict(outcome.validation),
            metadata=metadata,
            attempts=attempts,
            timings=timings,
            error=outcome.detail if outcome.status == "error" else None,
        )

    @property
    def language_detector(self) -> LanguageDetector:
        """Expose the language detector for instrumentation consumers."""

        return self._language

    @property
    def extractor(self) -> RulesExtractor:
        """Expose the extractor instance for instrumentation consumers."""

        return self._rules_extractor

    @property
    def llm_extractor(self) -> LLMExtractor:
        """Expose the LLM extractor for instrumentation consumers."""

        return self._llm_extractor

    @property
    def normalizer(self) -> Normalizer:
        """Expose the normalizer instance for instrumentation consumers."""

        return self._normalizer

    @property
    def validator(self) -> Validator:
        """Expose the validator instance for instrumentation consumers."""

        return self._validator

    @property
    def fixtures(self) -> FixtureRepository:
        """Return the fixture repository backing the pipeline."""

        return self._fixtures

    @property
    def configuration(self) -> SearchConfiguration:
        """Return the search configuration used across the pipeline."""

        return self._configuration


__all__ = ["HolidaySearchPipeline", "PipelineRunResult", "SearchConfiguration"]
