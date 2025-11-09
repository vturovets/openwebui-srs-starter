"""Dialog orchestration utilities for clarification flows."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from time import time
from typing import Dict, List, Mapping, MutableMapping
from uuid import uuid4

from ..config import Settings
from .normalizer import NormalizedResult
from .pipeline import HolidaySearchPipeline
from .validator import ValidationError


@dataclass(frozen=True)
class ClarificationRule:
    """Mapping between validation cues and clarification prompts."""

    parameter: str
    prompt: str
    keywords: tuple[str, ...]

    def matches(self, message: str) -> bool:
        lowered = message.lower()
        return any(keyword in lowered for keyword in self.keywords)


@dataclass
class ClarificationPrompt:
    """Prompt information returned to the client."""

    parameter: str
    message: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return {"parameter": self.parameter, "message": self.message, "reason": self.reason}


@dataclass
class DialogSession:
    """State container for an interactive clarification session."""

    identifier: str
    created_at: float = field(default_factory=time)
    turn: int = 0
    status: str = "pending"
    normalized: NormalizedResult | None = None
    transcript: List[MutableMapping[str, str]] = field(default_factory=list)
    missing_parameters: set[str] = field(default_factory=set)
    last_prompt: ClarificationPrompt | None = None
    method_requested: str | None = None
    method_used: str | None = None
    validation: Dict[str, object] = field(default_factory=dict)
    timings: Dict[str, float] = field(default_factory=dict)
    language: str | None = None
    language_confidence: float | None = None
    error: str | None = None
    llm_metadata: Dict[str, object] = field(default_factory=dict)

    def append_user_turn(self, text: str) -> None:
        self.turn += 1
        self.transcript.append({"role": "user", "text": text})

    def append_system_prompt(self, prompt: ClarificationPrompt) -> None:
        self.transcript.append({"role": "system", "text": prompt.message})
        self.last_prompt = prompt
        self.missing_parameters = {prompt.parameter}


@dataclass
class DialogTurnOutcome:
    """Return payload produced for each dialog turn."""

    status: str
    raw_status: str
    session_id: str | None
    data: Dict[str, object]
    prompt: ClarificationPrompt | None
    metadata: Dict[str, object]
    validation: Dict[str, object]
    missing_parameters: List[str]
    transcript: List[Mapping[str, str]]
    error: str | None = None


class DialogOrchestrator:
    """Inspect validation failures and surface clarification prompts."""

    _CLARIFICATION_RULES: tuple[ClarificationRule, ...] = (
        ClarificationRule(
            parameter="departureDate",
            prompt="I still need your departure date. When would you like to depart?",
            keywords=("departure date is required", "include departure date"),
        ),
        ClarificationRule(
            parameter="departureDate",
            prompt="That departure date is unavailable. Could you pick another travel date?",
            keywords=("departure date", "is not available"),
        ),
        ClarificationRule(
            parameter="from",
            prompt="Please choose a single departure airport so I can continue.",
            keywords=("multiple departure airports", "departure airport"),
        ),
        ClarificationRule(
            parameter="from",
            prompt="That departure airport isn't available. Could you select a different one?",
            keywords=("airport", "unavailable"),
        ),
        ClarificationRule(
            parameter="to",
            prompt="That destination isn't available. Please pick another holiday destination.",
            keywords=("destination", "unavailable"),
        ),
        ClarificationRule(
            parameter="to",
            prompt="Please pick just one destination so I know where you'd like to travel.",
            keywords=("multiple destinations", "too many destinations"),
        ),
        ClarificationRule(
            parameter="durationId",
            prompt="How many nights would you like to stay?",
            keywords=("duration is not supported",),
        ),
        ClarificationRule(
            parameter="party",
            prompt="Can you confirm how many adults and children are travelling?",
            keywords=("adult", "children", "infant"),
        ),
        ClarificationRule(
            parameter="rooms",
            prompt="How many rooms should I book for your stay?",
            keywords=("number of rooms", "rooms must be"),
        ),
    )

    def __init__(self, pipeline: HolidaySearchPipeline, settings: Settings) -> None:
        self._pipeline = pipeline
        self._settings = settings
        self._methods_catalog = pipeline.methods_catalog
        self._sessions: Dict[str, DialogSession] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def handle_turn(
        self,
        utterance: str,
        *,
        session_id: str | None = None,
        mode: str | None = None,
        method: str | None = None,
    ) -> DialogTurnOutcome:
        effective_mode = (mode or self._settings.interaction_mode or "direct-parse").strip().lower()
        if effective_mode != "dialog":
            result = self._pipeline.run(utterance, method=method)
            normalized_payload: Dict[str, object] = {}
            if result.normalized is not None and result.status != "error":
                normalized_payload = result.normalized.to_payload()

            pipeline_metadata = (
                result.metadata if isinstance(result.metadata, Mapping) else {}
            )
            timings = dict(result.timings)
            existing_timings = (
                pipeline_metadata.get("timings") if isinstance(pipeline_metadata, Mapping) else {}
            )
            if isinstance(existing_timings, Mapping):
                timings.update(existing_timings)
            metadata: Dict[str, object] = (
                {key: value for key, value in pipeline_metadata.items() if key != "timings"}
                if isinstance(pipeline_metadata, Mapping)
                else {}
            )
            metadata["mode"] = effective_mode
            metadata["method"] = result.method_used
            metadata["requestedMethod"] = result.method_requested
            metadata["timings"] = timings
            metadata["validation"] = dict(result.validation)
            metadata.setdefault("availableMethods", self._methods_catalog.to_metadata())
            metadata.setdefault("methodDefaults", dict(self._methods_catalog.defaults))
            metadata.setdefault("defaultMethod", self._methods_catalog.default_method_id)
            if result.detection is not None:
                metadata["language"] = {
                    "code": result.detection.language,
                    "confidence": result.detection.confidence,
                }
            metadata["transcript"] = [{"role": "user", "text": utterance}]
            metadata["missingParameters"] = []

            return DialogTurnOutcome(
                status=result.status,
                raw_status=result.status,
                session_id=None,
                data=normalized_payload,
                prompt=None,
                metadata=metadata,
                validation=dict(result.validation),
                missing_parameters=[],
                transcript=[{"role": "user", "text": utterance}],
                error=result.error,
            )

        session = self._get_or_create_session(session_id)
        session.append_user_turn(utterance)

        result = self._pipeline.run(utterance, method=method)

        session.method_requested = result.method_requested
        session.method_used = result.method_used
        session.validation = dict(result.validation)
        session.timings = dict(result.timings)
        llm_metadata = result.metadata.get("llm") if isinstance(result.metadata, Mapping) else None
        if isinstance(llm_metadata, Mapping):
            session.llm_metadata = dict(llm_metadata)
        else:
            session.llm_metadata = {}
        session.error = result.error

        if result.detection is not None:
            session.language = result.detection.language
            session.language_confidence = result.detection.confidence

        prompt: ClarificationPrompt | None = None
        error_message: str | None = None

        if result.status == "error":
            session.status = "failed"
            error_message = result.error
        else:
            normalized = result.normalized
            if normalized is not None:
                self._merge_normalized(session, normalized)

            aggregate_error = self._revalidate(session)
            if aggregate_error is None:
                session.status = "completed"
                session.missing_parameters.clear()
            else:
                prompt = self._select_prompt(aggregate_error, session.validation)
                if prompt is not None:
                    session.status = "pending"
                    session.append_system_prompt(prompt)
                    error_message = prompt.reason
                else:
                    session.status = "failed"
                    error_message = aggregate_error

        metadata = self._build_metadata(session, effective_mode)
        data_payload: Dict[str, object] = {}
        if session.normalized is not None and session.status in {"pending", "completed"}:
            data_payload = session.normalized.to_payload()

        missing_parameters = sorted(session.missing_parameters)

        status = session.status
        if status == "pending":
            status = "clarification"
        elif status == "completed":
            status = "success"

        return DialogTurnOutcome(
            status=status,
            raw_status=result.status,
            session_id=session.identifier,
            data=data_payload,
            prompt=prompt,
            metadata=metadata,
            validation=dict(session.validation),
            missing_parameters=missing_parameters,
            transcript=[dict(turn) for turn in session.transcript],
            error=error_message,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_or_create_session(self, session_id: str | None) -> DialogSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        identifier = session_id or uuid4().hex
        session = DialogSession(identifier=identifier)
        self._sessions[identifier] = session
        return session

    def _merge_normalized(self, session: DialogSession, normalized: NormalizedResult) -> None:
        if session.normalized is None:
            session.normalized = self._clone_normalized(normalized)
            return

        existing = session.normalized

        if normalized.language and normalized.language != existing.language:
            existing.language = normalized.language

        self._merge_unique(existing.from_codes, normalized.from_codes)
        self._merge_unique(existing.to_ids, normalized.to_ids)

        if normalized.departure_dates:
            existing.departure_dates = list(normalized.departure_dates)

        if normalized.duration_id:
            existing.duration_id = normalized.duration_id

        if normalized.party:
            existing.party.update(normalized.party)

        if normalized.rooms is not None:
            existing.rooms = normalized.rooms

        existing_context = existing.context
        new_context = normalized.context or {}

        self._merge_entity_context(existing_context, new_context, "airports")
        self._merge_entity_context(existing_context, new_context, "destinations")

        if new_context.get("dates_raw"):
            existing_context.setdefault("dates_raw", [])
            self._merge_unique(existing_context["dates_raw"], new_context["dates_raw"])

        if new_context.get("dates_base"):
            existing_context["dates_base"] = new_context["dates_base"]

        if new_context.get("flex_option"):
            existing_context["flex_option"] = new_context["flex_option"]

    def _revalidate(self, session: DialogSession) -> str | None:
        if session.normalized is None:
            return "No parameters collected yet"
        try:
            self._pipeline.validator.validate(session.normalized)
        except ValidationError as exc:
            session.validation = {
                "status": "failed",
                "errors": [{"message": str(exc)}],
            }
            return str(exc)
        else:
            session.validation = {"status": "passed", "errors": []}
            return None

    def _select_prompt(self, error_message: str, validation: Mapping[str, object]) -> ClarificationPrompt | None:
        errors: List[str] = []
        if error_message:
            errors.append(error_message)
        validation_errors = validation.get("errors") if isinstance(validation, Mapping) else []
        if isinstance(validation_errors, list):
            for item in validation_errors:
                message = ""
                if isinstance(item, Mapping):
                    message = str(item.get("message", ""))
                elif isinstance(item, str):
                    message = item
                if message:
                    errors.append(message)

        for message in errors:
            lowered = message.lower()
            for rule in self._CLARIFICATION_RULES:
                if rule.matches(lowered):
                    return ClarificationPrompt(parameter=rule.parameter, message=rule.prompt, reason=message)

        if errors:
            reason = errors[0]
            return ClarificationPrompt(
                parameter="general",
                message="Could you clarify the missing details so I can finish the search?",
                reason=reason,
            )
        return None

    def _build_metadata(self, session: DialogSession, mode: str) -> Dict[str, object]:
        metadata: Dict[str, object] = {
            "mode": mode,
            "method": session.method_used,
            "requestedMethod": session.method_requested,
            "timings": dict(session.timings),
            "validation": dict(session.validation),
            "turn": session.turn,
            "transcript": [dict(turn) for turn in session.transcript],
            "missingParameters": sorted(session.missing_parameters),
        }
        metadata.setdefault("availableMethods", self._methods_catalog.to_metadata())
        metadata.setdefault("methodDefaults", dict(self._methods_catalog.defaults))
        metadata.setdefault("defaultMethod", self._methods_catalog.default_method_id)
        if session.llm_metadata:
            metadata["llm"] = dict(session.llm_metadata)
        if session.language:
            metadata["language"] = {
                "code": session.language,
                "confidence": session.language_confidence,
            }
        if session.last_prompt is not None:
            metadata["lastPrompt"] = session.last_prompt.to_dict()
        if session.error:
            metadata["error"] = session.error
        return metadata

    @staticmethod
    def _merge_unique(existing: List[object], new_items: List[object]) -> None:
        for item in new_items:
            if item not in existing:
                existing.append(item)

    @staticmethod
    def _merge_entity_context(
        existing_context: MutableMapping[str, object],
        new_context: Mapping[str, object],
        key: str,
    ) -> None:
        if key not in new_context or not isinstance(new_context[key], list):
            return
        existing_list = existing_context.setdefault(key, [])
        if not isinstance(existing_list, list):
            existing_list = []
            existing_context[key] = existing_list
        for item in new_context[key]:
            serialised = json.dumps(item, sort_keys=True, default=str)
            if all(json.dumps(existing_item, sort_keys=True, default=str) != serialised for existing_item in existing_list):
                existing_list.append(item)

    @staticmethod
    def _clone_normalized(normalized: NormalizedResult) -> NormalizedResult:
        return NormalizedResult(
            language=normalized.language,
            from_codes=list(normalized.from_codes),
            to_ids=list(normalized.to_ids),
            departure_dates=list(normalized.departure_dates),
            duration_id=normalized.duration_id,
            party=dict(normalized.party),
            rooms=normalized.rooms,
            context=copy.deepcopy(normalized.context),
        )


__all__ = [
    "ClarificationPrompt",
    "DialogOrchestrator",
    "DialogTurnOutcome",
]
