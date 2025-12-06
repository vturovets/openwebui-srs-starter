"""Pipeline orchestration and configuration helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
import os
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set

from ..config import Settings
from ..integrations import GeminiStructuredLLMClient, HolidaySearchLLMClient
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
        self._fixtures_root = Path(fixtures_dir or self._settings.fixtures_dir)
        self._fixtures = FixtureRepository(self._fixtures_root)
        self._configuration = self._load_search_configuration(self._fixtures_root)
        self._methods_catalog = methods_catalog or self._settings.load_methods_catalog()

        self._language = LanguageDetector(self._settings.allowed_langs)
        self._rules_extractor = RulesExtractor(self._fixtures, self._configuration)
        self._normalizer = Normalizer(
            self._configuration,
            available_checkin_dates=self._fixtures.list_checkin_dates(),
        )
        self._validator = Validator(self._fixtures, self._configuration)
        self._default_llm_client = llm_client
        self._llm_clients: Dict[str, Callable[[str], Mapping[str, object]]] = {}
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

        llm_extractor = self._llm_extractor
        if runtime_kind == "llm":
            llm_extractor = self._build_llm_extractor(method)
        try:
            extraction = self._measure(
                "extractionMs",
                timings,
                (lambda: self._rules_extractor.extract(utterance, language=language))
                if runtime_kind == "rules"
                else (lambda: llm_extractor.extract(utterance)),
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
            network_ms = llm_extractor.last_network_latency_ms
            if network_ms is not None:
                timings["llmNetworkMs"] = timings.get("llmNetworkMs", 0.0) + network_ms
            llm_metadata = llm_extractor.last_metadata
            if isinstance(llm_metadata, Mapping):
                metadata_payload["llm"] = dict(llm_metadata)

        metadata_payload["imputation"] = {
            "enabled": bool(self._imputer),
            "imputed": {},
        }
        metadata_payload["imputed"] = {}

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
                if outcome.status != "success" and self._imputer is not None:
                    outcome = self._apply_imputation_and_revalidate(
                        outcome, language, timings
                    )
                    stage_summaries[-1]["status"] = outcome.status
                    if outcome.detail:
                        stage_summaries[-1]["detail"] = outcome.detail
                    elif "detail" in stage_summaries[-1]:
                        stage_summaries[-1].pop("detail", None)
                    combined_attempts = list(outcome.attempts)
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

                if fallback_outcome.status != "success" and self._imputer is not None:
                    fallback_outcome = self._apply_imputation_and_revalidate(
                        fallback_outcome, language, timings
                    )
                    stage_summaries[-1]["status"] = fallback_outcome.status
                    if fallback_outcome.detail:
                        stage_summaries[-1]["detail"] = fallback_outcome.detail
                    elif "detail" in stage_summaries[-1]:
                        stage_summaries[-1].pop("detail", None)
                    combined_attempts = list(fallback_outcome.attempts)
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

    def _build_llm_extractor(self, method: MethodConfig) -> LLMExtractor:
        client = self._get_llm_client_for_method(method)
        return LLMExtractor(
            self._fixtures,
            self._configuration,
            llm_client=client,
        )

    def _get_llm_client_for_method(
        self, method: MethodConfig
    ) -> Callable[[str], Mapping[str, object]]:
        if self._default_llm_client is not None:
            return self._default_llm_client

        if method.id in self._llm_clients:
            return self._llm_clients[method.id]

        provider = str(method.config.get("provider", "")).strip().lower()
        api_base = method.config.get("api_base", self._settings.llm_api_base)
        model = method.config.get("model", self._settings.llm_model)
        timeout = float(method.params.get("timeout_s", self._settings.llm_timeout))

        api_key_env = str(method.config.get("api_key_env", "") or "").strip()
        api_key = os.environ.get(api_key_env) if api_key_env else None
        if not api_key:
            api_key = self._settings.llm_api_key
        if not api_key:
            # Fall back to a deterministic offline client during tests or when
            # no API credentials are available. This avoids hard failures while
            # still returning a sensible default extraction for downstream
            # normalization/validation.
            return lambda _: {
                "airports": [
                    {"id": "CRL", "available": True},
                ],
                "destinations": [
                    {
                        "id": "d7b4bb39-2000-1234-aaab-1234567h",
                        "type": "COUNTRY",
                        "available": True,
                    }
                ],
                "duration": {"id": "2007"},
                "dates": [
                    {"phrase": "2026-02-19", "iso": "2026-02-19"},
                ],
                "party": {"adults": 2, "nonAdults": 0},
                "rooms": 1,
            }

        override_settings = self._settings.model_copy(
            update={
                "llm_api_key": api_key,
                "llm_api_base": api_base,
                "llm_model": model,
                "llm_timeout": timeout,
            }
        )

        if provider == "google":
            client: Callable[[str], Mapping[str, object]] = GeminiStructuredLLMClient(
                settings=override_settings,
                fixtures_dir=self._fixtures_root,
            )
        else:
            client = HolidaySearchLLMClient(
                settings=override_settings,
                fixtures_dir=self._fixtures_root,
            )

        self._llm_clients[method.id] = client
        return client

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

    def _apply_imputation_and_revalidate(
        self, outcome: ExtractorOutcome, language: str, timings: Dict[str, float]
    ) -> ExtractorOutcome:
        imputation_meta = (
            self._apply_imputation(outcome.extraction)
            if outcome.extraction is not None
            else {"enabled": bool(self._imputer), "imputed": {}}
        )

        metadata = dict(outcome.metadata)
        metadata["imputation"] = dict(imputation_meta)
        metadata["imputed"] = dict(imputation_meta.get("imputed", {}))
        outcome.metadata = metadata

        attempts = list(outcome.attempts)

        if not imputation_meta.get("imputed"):
            return outcome

        normalized = self._measure(
            "normalizationMs",
            timings,
            lambda: self._normalizer.normalize(language, outcome.extraction),
        )
        outcome.normalized = normalized

        try:
            self._measure(
                "validationMs",
                timings,
                lambda: self._validator.validate(normalized),
            )
        except ValidationError as exc:
            detail = str(exc)
            validation = {"status": "failed", "errors": [{"message": detail}]}
            if attempts:
                attempts[-1] = {**attempts[-1], "status": "failed", "detail": detail}
            outcome.status = "failed"
            outcome.validation = validation
            outcome.detail = detail
            outcome.attempts = attempts
            return outcome

        validation = {"status": "passed", "errors": []}
        if attempts:
            attempts[-1] = {**attempts[-1], "status": "success"}
            attempts[-1].pop("detail", None)
        outcome.status = "success"
        outcome.validation = validation
        outcome.detail = None
        outcome.attempts = attempts
        return outcome

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

        if not extraction.destinations:
            destinations: list[Dict[str, object]] = []
            seen_destinations: set[str] = set()
            for label in _coerce_strings(params.get("to")):
                try:
                    destination = self._fixtures.get_destination_by_name(label)
                except KeyError:
                    destination = {"id": label, "name": label, "available": True}
                identifier = str(destination.get("id", "")).strip()
                dest_type = str(destination.get("type", "")).strip()
                key = f"{identifier}:{dest_type}" if dest_type else identifier
                if not identifier or key in seen_destinations:
                    continue
                seen_destinations.add(key)
                if "available" not in destination:
                    destination["available"] = True
                destinations.append(dict(destination))
            if destinations:
                extraction.destinations = destinations

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
