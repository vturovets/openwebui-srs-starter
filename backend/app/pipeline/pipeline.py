"""Pipeline orchestration and configuration helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set

from ..config import Settings
from ..fixtures.repository import FixtureRepository
from .configuration import (
    HybridMethodConfig,
    MethodConfig,
    MethodsCatalog,
    SearchConfiguration,
)
from .extractor_rules import ExtractionResult, RulesExtractor
from .extractors import ExtractorOutcome, LLMExtractor
from .language import LanguageDetector, LanguageDetectionResult
from .normalizer import Normalizer, NormalizedResult
from .validator import ValidationError, Validator
from ..services.popularity_imputer import PopularityImputer


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


def extraction_to_imputer_payload(extraction: ExtractionResult) -> Dict[str, object]:
    """Convert an extraction result into a popularity imputer payload."""

    def _collect_labels(entities: Sequence[Mapping[str, object]]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            label = str(entity.get("name") or entity.get("id") or "").strip()
            if not label:
                continue
            lowered = label.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            labels.append(label)
        return labels

    airports = _collect_labels(extraction.airports)
    destinations = _collect_labels(extraction.destinations)
    dates = [dt.isoformat() for _, dt in extraction.dates]

    duration_id: str | None = None
    if extraction.duration:
        duration_id = str(extraction.duration.get("id", "")).strip() or None

    party_payload: Dict[str, int] = {}
    if isinstance(extraction.party, Mapping):
        adults = extraction.party.get("adults")
        non_adults = extraction.party.get("nonAdults")
        if adults is not None and non_adults is not None:
            party_payload = {
                "adults": int(adults),
                "nonAdults": int(non_adults),
            }

    payload: Dict[str, object] = {
        "from": airports,
        "to": destinations,
        "durationId": duration_id,
        "departureDate": dates,
        "party": party_payload,
        "rooms": extraction.rooms,
    }
    return payload


class HolidaySearchPipeline:
    """Co-ordinate language detection, extraction, normalisation, and validation."""

    CONFIG_FILENAME = "configuration_search.json"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        fixtures_dir: str | Path | None = None,
        llm_client: Callable[[str], Mapping[str, object]] | None = None,
        methods_catalog: MethodsCatalog | None = None,
    ) -> None:
        self._settings = settings or Settings()
        fixtures_root = Path(fixtures_dir or self._settings.fixtures_dir)
        self._fixtures = FixtureRepository(fixtures_root)
        self._configuration = self._load_search_configuration(fixtures_root)
        self._methods_catalog = methods_catalog or self._settings.load_methods_catalog()

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
        self._imputer: PopularityImputer | None = None
        if self._settings.popularity_imputer_enabled:
            self._imputer = PopularityImputer(
                settings=self._settings,
                configuration=self._configuration,
            )

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
        method: MethodConfig,
        utterance: str,
        language: str,
        timings: Dict[str, float],
    ) -> ExtractorOutcome:
        runtime_kind = method.kind
        metadata_payload: Dict[str, Any] = {
            "methodId": method.id,
            "methodType": runtime_kind,
        }
        attempts: List[Dict[str, Any]] = [
            {
                "method": method.id,
                "type": runtime_kind,
            }
        ]
        try:
            extraction = self._measure(
                "extractionMs",
                timings,
                (lambda: self._rules_extractor.extract(utterance, language=language))
                if runtime_kind == "rules"
                else (lambda: self._llm_extractor.extract(utterance)),
            )
        except ValueError as exc:
            detail = str(exc)
            validation = {
                "status": "error",
                "errors": [{"message": detail}],
            }
            attempts[0]["status"] = "error"
            attempts[0]["detail"] = detail
            return ExtractorOutcome(
                method=method.id,
                status="error",
                extraction=None,
                normalized=None,
                validation=validation,
                detail=detail,
                attempts=attempts,
                metadata=metadata_payload,
            )

        if runtime_kind == "llm":
            network_ms = self._llm_extractor.last_network_latency_ms
            if network_ms is not None:
                timings["llmNetworkMs"] = timings.get("llmNetworkMs", 0.0) + network_ms
            llm_metadata = self._llm_extractor.last_metadata
            if isinstance(llm_metadata, Mapping):
                metadata_payload["llm"] = dict(llm_metadata)

        imputation_meta = self._apply_imputation(extraction)
        metadata_payload["imputation"] = dict(imputation_meta)
        metadata_payload["imputed"] = dict(imputation_meta.get("imputed", {}))

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
            attempts[0]["status"] = "failed"
            attempts[0]["detail"] = detail
            return ExtractorOutcome(
                method=method.id,
                status="failed",
                extraction=extraction,
                normalized=normalized,
                validation=validation,
                detail=detail,
                attempts=attempts,
                metadata=metadata_payload,
            )

        validation = {"status": "passed", "errors": []}
        attempts[0]["status"] = "success"
        return ExtractorOutcome(
            method=method.id,
            status="success",
            extraction=extraction,
            normalized=normalized,
            validation=validation,
            attempts=attempts,
            metadata=metadata_payload,
        )

    def _execute_hybrid(
        self,
        method: HybridMethodConfig,
        utterance: str,
        language: str,
        timings: Dict[str, float],
        *,
        visited: Set[str],
    ) -> ExtractorOutcome:
        if method.id in visited:
            raise ValueError(f"Detected recursive hybrid execution for '{method.id}'")
        visited.add(method.id)
        combined_attempts: List[Dict[str, Any]] = []
        stage_summaries: List[Dict[str, Any]] = []
        last_outcome: Optional[ExtractorOutcome] = None
        try:
            for stage in method.stages:
                outcome = self._execute_method(stage.method, utterance, language, timings, visited=visited)
                stage_summary: Dict[str, Any] = {
                    "id": stage.method.id,
                    "type": stage.method.kind,
                    "status": outcome.status,
                }
                if outcome.detail:
                    stage_summary["detail"] = outcome.detail
                stage_summaries.append(stage_summary)
                combined_attempts.extend(dict(attempt) for attempt in outcome.attempts)
                last_outcome = outcome
                if outcome.status == "success":
                    metadata = dict(outcome.metadata)
                    metadata.update({"methodId": method.id, "methodType": method.kind})
                    metadata["hybrid"] = {
                        "methodId": method.id,
                        "strategy": method.strategy,
                        "stages": stage_summaries,
                        "selectedStage": stage.method.id,
                        "fallbackTriggered": False,
                    }
                    outcome.metadata = metadata
                    outcome.attempts = combined_attempts
                    return outcome

            if method.fallback is not None:
                fallback_outcome = self._execute_method(method.fallback, utterance, language, timings, visited=visited)
                fallback_summary: Dict[str, Any] = {
                    "id": method.fallback.id,
                    "type": method.fallback.kind,
                    "status": fallback_outcome.status,
                    "fallback": True,
                }
                if fallback_outcome.detail:
                    fallback_summary["detail"] = fallback_outcome.detail
                stage_summaries.append(fallback_summary)
                combined_attempts.extend(dict(attempt) for attempt in fallback_outcome.attempts)
                metadata = dict(fallback_outcome.metadata)
                hybrid_meta: Dict[str, Any] = {
                    "methodId": method.id,
                    "strategy": method.strategy,
                    "stages": stage_summaries,
                    "selectedStage": fallback_outcome.method if fallback_outcome.status == "success" else None,
                    "fallbackTriggered": True,
                    "fallback": method.fallback.id,
                }
                if fallback_outcome.detail:
                    hybrid_meta["fallbackDetail"] = fallback_outcome.detail
                metadata.update({"methodId": method.id, "methodType": method.kind})
                metadata["hybrid"] = hybrid_meta
                fallback_outcome.metadata = metadata
                fallback_outcome.attempts = combined_attempts
                return fallback_outcome

            if last_outcome is None:
                raise RuntimeError(f"Hybrid method '{method.id}' did not execute any stages")
            metadata = dict(last_outcome.metadata)
            metadata["hybrid"] = {
                "methodId": method.id,
                "strategy": method.strategy,
                "stages": stage_summaries,
                "selectedStage": None,
                "fallbackTriggered": False,
            }
            last_outcome.metadata = metadata
            if combined_attempts:
                last_outcome.attempts = combined_attempts
            return last_outcome
        finally:
            visited.discard(method.id)

    def _execute_method(
        self,
        method: MethodConfig,
        utterance: str,
        language: str,
        timings: Dict[str, float],
        *,
        visited: Optional[Set[str]] = None,
    ) -> ExtractorOutcome:
        visited_set = visited or set()
        if isinstance(method, HybridMethodConfig):
            return self._execute_hybrid(method, utterance, language, timings, visited=visited_set)
        if method.kind not in {"rules", "llm"}:
            raise ValueError(f"Unsupported method kind '{method.kind}' requested")
        return self._run_single_pass(method, utterance, language, timings)

    def _resolve_method(self, override: str | None) -> tuple[str | None, MethodConfig]:
        candidate = override or self._settings.llm_method
        alias = candidate.strip() if isinstance(candidate, str) else None
        if alias:
            method = self._methods_catalog.lookup(alias)
            if method is not None:
                return alias, method
        return alias, self._methods_catalog.default_method

    def run(self, utterance: str, *, method: str | None = None) -> PipelineRunResult:
        timings: Dict[str, float] = {}
        total_start = perf_counter()

        detection = self._measure(
            "languageMs",
            timings,
            lambda: self._language.detect(utterance),
        )

        requested_alias, resolved_method = self._resolve_method(method)
        outcome = self._execute_method(resolved_method, utterance, detection.language, timings)

        total_ms = (perf_counter() - total_start) * 1000
        timings["totalMs"] = total_ms

        metadata = dict(outcome.metadata)
        metadata.setdefault("methodId", resolved_method.id)
        metadata.setdefault("methodType", resolved_method.kind)
        if requested_alias and requested_alias.lower() != resolved_method.id.lower():
            metadata.setdefault("requestedAlias", requested_alias)
        metadata.setdefault("availableMethods", self._methods_catalog.to_metadata())
        metadata.setdefault("methodDefaults", dict(self._methods_catalog.defaults))
        metadata.setdefault("defaultMethod", self._methods_catalog.default_method_id)
        metadata.setdefault("catalogSize", len(self._methods_catalog.list_methods()))
        metadata.setdefault("imputed", metadata.get("imputed", {}))
        attempts = [dict(item) for item in outcome.attempts]

        normalized = outcome.normalized
        if not isinstance(normalized, NormalizedResult):
            normalized = None

        return PipelineRunResult(
            status=outcome.status,
            method_requested=resolved_method.id,
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

    @property
    def methods_catalog(self) -> MethodsCatalog:
        """Expose the configured methods catalogue."""

        return self._methods_catalog

    @property
    def default_method_id(self) -> str:
        """Shortcut for the default method identifier."""

        return self._methods_catalog.default_method_id

    def _apply_imputation(self, extraction: ExtractionResult) -> Dict[str, object]:
        if self._imputer is None:
            return {"enabled": False, "imputed": {}}

        params = extraction_to_imputer_payload(extraction)
        enriched, metadata = self._imputer.impute(params)
        self._merge_imputed_values(extraction, enriched)
        metadata.setdefault("imputed", {})
        metadata.setdefault("enabled", True)
        return metadata

    def _merge_imputed_values(self, extraction: ExtractionResult, params: Mapping[str, object]) -> None:
        def _coerce_strings(value: object) -> list[str]:
            if isinstance(value, str):
                candidates = [value]
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                candidates = list(value)
            else:
                candidates = []
            results: list[str] = []
            for item in candidates:
                if not isinstance(item, str):
                    continue
                cleaned = item.strip()
                if cleaned:
                    results.append(cleaned)
            return results

        if not extraction.airports:
            airports: list[Dict[str, object]] = []
            seen: set[str] = set()
            for label in _coerce_strings(params.get("from")):
                try:
                    airport = self._fixtures.get_airport_by_name(label)
                except KeyError:
                    airport = {"id": label.upper(), "name": label, "available": True}
                if "available" not in airport:
                    airport["available"] = True
                code = str(airport.get("id", "")).upper()
                if not code or code in seen:
                    continue
                seen.add(code)
                airports.append(dict(airport))
            if airports:
                extraction.airports = airports

        if not extraction.dates:
            dates: list[tuple[str, datetime]] = []
            for iso_value in _coerce_strings(params.get("departureDate")):
                try:
                    parsed = datetime.fromisoformat(iso_value)
                except ValueError:
                    continue
                dates.append((iso_value, parsed))
            if dates:
                extraction.dates = dates

        if extraction.duration is None or not str(extraction.duration.get("id", "")).strip():
            duration_id = params.get("durationId")
            if isinstance(duration_id, str) and duration_id.strip():
                meta = self._configuration.duration_by_id.get(duration_id.strip())
                if meta:
                    extraction.duration = dict(meta)

        if not isinstance(extraction.party, Mapping):
            party_payload = params.get("party")
            if isinstance(party_payload, Mapping):
                adults = party_payload.get("adults")
                non_adults = party_payload.get("nonAdults")
                if adults is not None and non_adults is not None:
                    extraction.party = {
                        "adults": int(adults),
                        "nonAdults": int(non_adults),
                    }

        if extraction.rooms is None and params.get("rooms") is not None:
            rooms_value = params.get("rooms")
            try:
                extraction.rooms = int(rooms_value) if rooms_value is not None else None
            except (TypeError, ValueError):
                extraction.rooms = None


__all__ = [
    "HolidaySearchPipeline",
    "PipelineRunResult",
    "SearchConfiguration",
    "extraction_to_imputer_payload",
]
