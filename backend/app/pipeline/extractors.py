"""Extractor strategies for advanced pipeline behaviours."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Callable, List, Mapping, MutableMapping, Sequence

from ..fixtures.repository import FixtureRepository
from ..integrations.llm import LLMClientHandle
from .configuration import MethodConfig, SearchConfiguration
from .extractor_rules import ExtractionResult, RulesExtractor


@dataclass
class ExtractionAttempt:
    """Record of a single extractor attempt."""

    method: str
    status: str
    detail: str | None = None


@dataclass
class ExtractorOutcome:
    """Outcome returned by extractor strategies."""

    method: str
    status: str
    extraction: ExtractionResult | None
    normalized: object | None
    validation: MutableMapping[str, object]
    detail: str | None = None
    attempts: List[Mapping[str, object]] = field(default_factory=list)
    metadata: MutableMapping[str, object] = field(default_factory=dict)


class LLMExtractor:
    """Adapter around an LLM client returning extraction signals."""

    def __init__(
        self,
        fixtures: FixtureRepository,
        configuration: SearchConfiguration,
        *,
        llm_registry: Mapping[str, LLMClientHandle] | None = None,
        llm_client: Callable[[str], Mapping[str, object]] | LLMClientHandle | None = None,
        default_method_id: str | None = None,
    ) -> None:
        self._fixtures = fixtures
        self._configuration = configuration
        self._llm_registry: dict[str, LLMClientHandle] | None = None
        if llm_registry is not None:
            self._llm_registry = dict(llm_registry)

        self._default_handle: LLMClientHandle | None = None
        if llm_client is not None:
            if isinstance(llm_client, LLMClientHandle):
                handle = llm_client
            else:
                method_id = default_method_id or "default-llm"
                handle = LLMClientHandle(
                    method_id=method_id,
                    provider="custom",
                    client=llm_client,
                )
            self._default_handle = handle
            if self._llm_registry is None:
                self._llm_registry = {handle.method_id: handle}
            else:
                self._llm_registry.setdefault(handle.method_id, handle)

        self._last_network_latency_ms: float | None = None
        self._last_metadata: MutableMapping[str, object] | None = None
        self._last_handle: LLMClientHandle | None = None

        # Snapshot fixture metadata for quick lookup.
        self._airports_by_id = {entry["id"]: entry for entry in fixtures.list_airports()}
        self._destinations_by_id = {entry["id"]: entry for entry in fixtures.list_destinations()}
        self._durations_by_id = configuration.duration_by_id
        self._flex_by_id = configuration.flex_by_id

    def _lookup_airport(self, identifier: str) -> Mapping[str, object]:
        try:
            return self._airports_by_id[identifier.upper()]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unknown departure airport '{identifier}' returned by LLM") from exc

    def _lookup_destination(self, identifier: str) -> Mapping[str, object]:
        key = identifier.strip()
        try:
            return self._destinations_by_id[key]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unknown destination '{identifier}' returned by LLM") from exc

    def _coerce_dates(self, payload: Mapping[str, object]) -> Sequence[tuple[str, datetime]]:
        results: List[tuple[str, datetime]] = []
        raw_dates = payload.get("dates", [])
        for item in raw_dates:
            if isinstance(item, str):
                phrase = item
                iso_value = item
            elif isinstance(item, Mapping):
                phrase = str(item.get("phrase") or item.get("text") or item.get("iso"))
                iso_value = str(item.get("iso") or item.get("value") or item.get("date"))
            else:
                raise ValueError("LLM extractor received unsupported date representation")

            try:
                parsed = datetime.fromisoformat(iso_value)
            except ValueError as exc:  # pragma: no cover - invalid LLM payloads
                raise ValueError(f"LLM returned invalid ISO date '{iso_value}'") from exc
            results.append((phrase, parsed))
        return results

    def extract(self, utterance: str, *, method: MethodConfig | None = None) -> ExtractionResult:
        if self._llm_registry is None and self._default_handle is None:
            raise ValueError("LLM extractor is not configured")

        self._last_handle = None
        handle: LLMClientHandle | None = None
        method_identifier: str | None = None

        if method is not None and self._llm_registry is not None:
            method_identifier = method.id
            handle = self._llm_registry.get(method.id)
            if handle is None:
                provider_hint = str(method.config.get("provider")) if method.config else ""
                for candidate in self._llm_registry.values():
                    if candidate.provider == provider_hint and provider_hint:
                        handle = candidate
                        break

        if handle is None and self._llm_registry is not None and len(self._llm_registry) == 1:
            handle = next(iter(self._llm_registry.values()))
            method_identifier = handle.method_id

        if handle is None:
            handle = self._default_handle

        if handle is None:
            if method_identifier:
                raise ValueError(f"LLM method '{method_identifier}' is not configured")
            raise ValueError("LLM extractor is not configured")

        self._last_handle = handle
        self._last_network_latency_ms = None
        self._last_metadata = {}
        start = perf_counter()
        payload = handle.client(utterance)
        self._last_network_latency_ms = (perf_counter() - start) * 1000
        if not isinstance(payload, Mapping):
            raise ValueError("LLM extractor must return a mapping payload")

        metadata_payload: MutableMapping[str, object] = {}
        for key in ("_metadata", "metadata", "meta", "llm"):
            candidate = payload.get(key)
            if isinstance(candidate, Mapping):
                metadata_payload.update(candidate)

        for key in (
            "provider",
            "engine",
            "model",
            "promptId",
            "responseId",
            "requestId",
            "traceId",
        ):
            value = payload.get(key)
            if value is not None and value != "":
                metadata_payload.setdefault(key, value)

        metadata_payload.setdefault("provider", handle.provider)
        if handle.model and "model" not in metadata_payload:
            metadata_payload["model"] = handle.model
        metadata_payload.setdefault("methodId", handle.method_id)
        if isinstance(handle.config, Mapping):
            provider_config = {
                key: value
                for key, value in handle.config.items()
                if key in {"provider", "api_base", "model"}
            }
            if provider_config:
                metadata_payload.setdefault("config", provider_config)

        self._last_metadata = metadata_payload

        airports: List[Mapping[str, object]] = []
        for item in payload.get("airports", []):
            if isinstance(item, Mapping):
                airports.append(dict(item))
            else:
                airports.append(dict(self._lookup_airport(str(item))))

        destinations: List[Mapping[str, object]] = []
        for item in payload.get("destinations", []):
            if isinstance(item, Mapping):
                destinations.append(dict(item))
            else:
                destinations.append(dict(self._lookup_destination(str(item))))

        duration_payload = payload.get("duration")
        if isinstance(duration_payload, Mapping):
            duration = dict(duration_payload)
        elif duration_payload is not None:
            duration = dict(self._durations_by_id.get(str(duration_payload), {}))
        else:
            duration = None

        flexibility_payload = payload.get("flexibility")
        if isinstance(flexibility_payload, Mapping):
            flexibility = dict(flexibility_payload)
        elif flexibility_payload is not None:
            flexibility = dict(self._flex_by_id.get(str(flexibility_payload), {}))
        else:
            flexibility = None

        dates = list(self._coerce_dates(payload))

        return ExtractionResult(
            airports=list(airports),
            destinations=list(destinations),
            duration=duration,
            flexibility=flexibility,
            dates=dates,
        )

    @property
    def last_network_latency_ms(self) -> float | None:
        """Return the most recent latency measurement for the LLM client."""

        return self._last_network_latency_ms

    @property
    def last_metadata(self) -> MutableMapping[str, object] | None:
        """Expose the last structured metadata payload returned by the LLM."""

        if self._last_metadata is None:
            return None
        return dict(self._last_metadata)

    @property
    def last_handle(self) -> LLMClientHandle | None:
        """Return the last client handle used for extraction."""

        return self._last_handle


class HybridExtractor:
    """Orchestrate rules-first extraction with LLM fallback."""

    def __init__(self, rules: RulesExtractor, llm: LLMExtractor) -> None:
        self._rules = rules
        self._llm = llm

    def run(
        self,
        *,
        run_rules: Callable[[], ExtractorOutcome],
        run_llm: Callable[[], ExtractorOutcome],
    ) -> ExtractorOutcome:
        rules_outcome = run_rules()
        attempts = list(rules_outcome.attempts)

        if rules_outcome.status != "failed":
            metadata = {
                "fallbackTriggered": False,
                "attempts": attempts,
            }
            if rules_outcome.detail:
                metadata["primaryDetail"] = rules_outcome.detail
            rules_outcome.metadata = {**rules_outcome.metadata, "hybrid": metadata}
            rules_outcome.attempts = attempts
            return rules_outcome

        # Validation failed – attempt LLM fallback.
        fallback_outcome = run_llm()
        attempts.extend(fallback_outcome.attempts)
        metadata = {
            "fallbackTriggered": True,
            "attempts": attempts,
            "primaryFailure": rules_outcome.detail,
        }
        fallback_outcome.metadata = {**fallback_outcome.metadata, "hybrid": metadata}
        fallback_outcome.attempts = attempts
        return fallback_outcome


__all__ = [
    "ExtractionAttempt",
    "ExtractorOutcome",
    "HybridExtractor",
    "LLMExtractor",
]
