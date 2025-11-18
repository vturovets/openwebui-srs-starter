"""Versioned API route definitions for the OpenWebUI SRS backend."""

from __future__ import annotations

import json
import mimetypes
import re
from time import perf_counter, perf_counter_ns
from collections.abc import Mapping

from datetime import datetime, timezone
from typing import AsyncIterator, Iterable, cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.params import Depends as DependsMarker
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..dependencies import (
    get_csv_logger,
    get_dialog_orchestrator,
    get_auto_completion_service,
    get_import_summary_logger,
    get_stt_client,
    get_pipeline,
    get_settings,
)
from ..logging import CSVLogger, ImportSummaryLogger
from ..pipeline.dialog import DialogOrchestrator
from ..pipeline.pipeline import HolidaySearchPipeline
from ..schemas import ImportSummary as ImportSummarySchema, build_import_summary
from ..services import (
    AutoCompletionService,
    GuardrailOverloadError,
    ImportJobRunner,
    ImportSummary as ImportSummaryData,
)
from ..integrations.stt import (
    SpeechToTextClient,
    SpeechToTextError,
    TranscriptionResult,
)

api_router = APIRouter(prefix="/v1", tags=["v1"])


_DEPENDENCY_RESOLVERS = {
    get_pipeline: get_pipeline,
    get_csv_logger: get_csv_logger,
    get_import_summary_logger: get_import_summary_logger,
    get_stt_client: get_stt_client,
}


def _resolve_dependency(value: object) -> object:
    """Resolve FastAPI dependency markers when invoking endpoints directly."""

    if isinstance(value, DependsMarker):
        dependency = getattr(value, "dependency", None)
        resolver = _DEPENDENCY_RESOLVERS.get(dependency)
        if resolver is not None:
            return resolver()
    return value


def _resolve_suggestions_limit(settings: Settings) -> int:
    """Return a sane suggestions limit based on configuration."""

    try:
        configured_limit = int(settings.suggestions_limit)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        return 1
    return max(1, configured_limit)


def _utc_timestamp() -> str:
    """Return an ISO 8601 timestamp with millisecond precision in UTC."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class BatchParseItem(BaseModel):
    """Discrete parse request for use within import batches."""

    text: str = Field(..., description="Utterance to parse for this batch item.")
    mode: str | None = Field(
        default=None,
        description="Optional interaction mode override supplied by the UI.",
    )
    method: str | None = Field(
        default=None,
        description="Optional method identifier to attribute downstream processing.",
    )


class ParseRequest(BaseModel):
    """Payload required to invoke the NLP pipeline."""

    text: str = Field(..., description="Utterance to parse.")
    mode: str | None = Field(
        default=None,
        description="Optional interaction mode override supplied by the UI.",
    )
    method: str | None = Field(
        default=None,
        description="Optional method identifier to attribute downstream processing.",
    )
    batch: list[BatchParseItem] | str | None = Field(
        default=None,
        description=(
            "Optional batch payload when running bulk imports. Accepts a list of "
            "ParseRequest-compatible items or a storage key reference."
        ),
    )
    import_mode: bool = Field(
        default=False,
        description="Flag indicating whether the request should trigger import execution.",
    )

    model_config = ConfigDict(populate_by_name=True)


class VoiceWordTiming(BaseModel):
    """Word-level timing returned by the STT provider."""

    word: str
    start: float
    end: float


class VoiceResponse(BaseModel):
    """Structured response for the voice endpoint."""

    status: str
    voice_enabled: bool
    engine: str | None
    transcript: str | None
    words: list[VoiceWordTiming] = Field(default_factory=list)
    data: dict[str, object] | None = None
    metadata: dict[str, object]


class ParseResponse(BaseModel):
    """Structured response returned by the parse endpoint."""

    status: str
    data: dict[str, object]
    metadata: dict[str, object]


class ClarificationPayload(BaseModel):
    """Structured clarification prompt returned to the UI."""

    parameter: str
    message: str
    reason: str


class DialogRequest(BaseModel):
    """Request payload supporting interactive clarification."""

    text: str = Field(..., description="User utterance for this dialog turn.")
    session_id: str | None = Field(
        default=None,
        alias="sessionId",
        description="Identifier for the dialog session; omitted to start a new one.",
    )
    mode: str | None = Field(
        default=None,
        description="Interaction mode override (e.g. 'dialog' or 'direct-parse').",
    )
    method: str | None = Field(
        default=None,
        description="Optional method identifier forwarded to the pipeline.",
    )

    model_config = ConfigDict(populate_by_name=True)


class DialogResponse(BaseModel):
    """Response payload for dialog-aware requests."""

    status: str
    session_id: str | None = Field(default=None, alias="sessionId")
    data: dict[str, object]
    prompt: ClarificationPayload | None = None
    metadata: dict[str, object]

    model_config = ConfigDict(populate_by_name=True)


_FIELD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"departure\s+date"), "departureDate"),
    (re.compile(r"departure(?!\s+date)"), "from"),
    (re.compile(r"airport"), "from"),
    (re.compile(r"destination"), "to"),
    (re.compile(r"arrival"), "to"),
    (re.compile(r"duration"), "durationId"),
    (re.compile(r"night"), "durationId"),
    (re.compile(r"room"), "rooms"),
    (re.compile(r"adult"), "party"),
    (re.compile(r"child"), "party"),
    (re.compile(r"infant"), "party"),
    (re.compile(r"flex"), "flexibility"),
)

_MISSING_KEYWORDS = ("require", "missing", "must include", "need")
_INVALID_KEYWORDS = (
    "unavailable",
    "not allowed",
    "not supported",
    "too many",
    "exceed",
    "cannot",
    "not available",
)


def _sniff_audio_content_type(prefix: bytes) -> str | None:
    """Return a MIME type guess based on well-known audio container signatures."""

    if len(prefix) >= 12 and prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE":
        return "audio/wav"
    if prefix.startswith(b"OggS"):
        return "audio/ogg"
    if prefix.startswith(b"fLaC"):
        return "audio/flac"
    if prefix.startswith(b"\x1A\x45\xDF\xA3"):
        # Matroska container, used for both audio/webm and video/webm. The UI microphone
        # recorder yields WebM blobs, so prefer the more permissive video/webm type which
        # is already whitelisted.
        return "video/webm"
    if prefix.startswith(b"ID3"):
        return "audio/mpeg"
    if len(prefix) >= 2 and prefix[0] == 0xFF and prefix[1] & 0xE0 == 0xE0:
        # MP3 frame sync header.
        return "audio/mpeg"
    return None


async def _resolve_missing_audio_content_type(
    audio: UploadFile, raw_content_type: str, base_content_type: str
) -> tuple[str, str, bytes]:
    """Augment missing content type metadata by guessing from file hints."""

    guessed_type, _ = mimetypes.guess_type(audio.filename or "")
    guessed_type = (guessed_type or "").lower()
    if guessed_type:
        base_type = guessed_type.split(";")[0].strip() or guessed_type
        if not raw_content_type or raw_content_type == "application/octet-stream":
            raw_content_type = guessed_type
        return raw_content_type, base_type, b""

    sniff_leading_bytes = b""
    try:
        await audio.seek(0)
    except (AttributeError, TypeError, OSError):
        # Some upload implementations may not support seeking; ignore and attempt to read
        # from the current position which should be at the start for brand new uploads.
        pass

    sniff_bytes = await audio.read(32)
    detected_type = _sniff_audio_content_type(sniff_bytes)

    try:
        await audio.seek(0)
    except (AttributeError, TypeError, OSError):
        sniff_leading_bytes = sniff_bytes

    if detected_type:
        base_content_type = detected_type.split(";")[0].strip() or detected_type
        if not raw_content_type or raw_content_type == "application/octet-stream":
            raw_content_type = detected_type

    return raw_content_type, base_content_type, sniff_leading_bytes


def _fields_from_message(message: str) -> set[str]:
    lowered = message.lower()
    fields = {field for pattern, field in _FIELD_PATTERNS if pattern.search(lowered)}
    return fields


def _normalized_has_field(normalized: object, field: str) -> bool:
    if normalized is None:
        return False
    match field:
        case "from":
            return bool(getattr(normalized, "from_codes", []))
        case "to":
            return bool(getattr(normalized, "to_ids", []))
        case "departureDate":
            return bool(getattr(normalized, "departure_dates", []))
        case "durationId":
            return bool(getattr(normalized, "duration_id", ""))
        case "rooms":
            rooms = getattr(normalized, "rooms", None)
            return rooms is not None and rooms != ""
        case "party":
            party = getattr(normalized, "party", {})
            if isinstance(party, Mapping):
                return bool(party.get("adults", 0) or party.get("nonAdults", 0))
            return False
        case "flexibility":
            context = getattr(normalized, "context", {})
            if isinstance(context, Mapping):
                return bool(context.get("flex_option"))
            return False
        case _:
            return False


def _derive_missing_fields(result) -> list[str]:
    missing: set[str] = set()
    normalized = getattr(result, "normalized", None)
    if normalized is None:
        missing.update({"from", "to", "departureDate"})
    else:
        if not getattr(normalized, "from_codes", []):
            missing.add("from")
        if not getattr(normalized, "to_ids", []):
            missing.add("to")
        if not getattr(normalized, "departure_dates", []):
            missing.add("departureDate")

    validation = getattr(result, "validation", {})
    errors: list[Mapping[str, object]] = []
    if isinstance(validation, Mapping):
        raw_errors = validation.get("errors", []) or []
        if isinstance(raw_errors, list):
            errors = [item for item in raw_errors if isinstance(item, Mapping)]

    for error in errors:
        message = str(error.get("message", ""))
        lowered = message.lower()
        if not lowered:
            continue
        if any(keyword in lowered for keyword in _MISSING_KEYWORDS):
            fields = _fields_from_message(lowered)
            if not fields:
                continue
            for field in fields:
                if normalized is not None and _normalized_has_field(normalized, field):
                    continue
                missing.add(field)

    return sorted(missing)


def _derive_invalid_fields(result) -> list[str]:
    invalid: set[str] = set()
    validation = getattr(result, "validation", {})
    errors: list[Mapping[str, object]] = []
    if isinstance(validation, Mapping):
        raw_errors = validation.get("errors", []) or []
        if isinstance(raw_errors, list):
            errors = [item for item in raw_errors if isinstance(item, Mapping)]

    for error in errors:
        message = str(error.get("message", ""))
        lowered = message.lower()
        if not lowered:
            continue
        if any(keyword in lowered for keyword in _INVALID_KEYWORDS):
            fields = _fields_from_message(lowered)
            if not fields:
                continue
            invalid.update(fields)

    return sorted(invalid)


def _extract_recognized_entities(result) -> dict[str, object]:
    extraction = getattr(result, "extraction", None)
    recognized = {
        "airports": [],
        "destinations": [],
        "dates": [],
        "duration": None,
        "flexibility": None,
    }
    if extraction is None:
        return recognized

    airports: list[str] = []
    for entry in getattr(extraction, "airports", []) or []:
        identifier = ""
        if isinstance(entry, Mapping):
            identifier = str(entry.get("id") or entry.get("code") or entry.get("name") or "").strip()
        else:
            identifier = str(entry).strip()
        if identifier:
            airports.append(identifier)

    destinations: list[str] = []
    for entry in getattr(extraction, "destinations", []) or []:
        identifier = ""
        if isinstance(entry, Mapping):
            identifier = str(entry.get("id") or entry.get("name") or "").strip()
        else:
            identifier = str(entry).strip()
        if identifier:
            destinations.append(identifier)

    dates: list[str] = []
    for item in getattr(extraction, "dates", []) or []:
        phrase, dt = item
        try:
            dates.append(dt.isoformat())
        except AttributeError:
            continue

    duration_value = None
    duration_meta = getattr(extraction, "duration", None)
    if isinstance(duration_meta, Mapping):
        duration_value = str(duration_meta.get("id") or duration_meta.get("name") or "").strip() or None

    flexibility_value = None
    flexibility_meta = getattr(extraction, "flexibility", None)
    if isinstance(flexibility_meta, Mapping):
        flexibility_value = (
            str(flexibility_meta.get("id") or flexibility_meta.get("name") or "").strip() or None
        )

    recognized["airports"] = airports
    recognized["destinations"] = destinations
    recognized["dates"] = dates
    recognized["duration"] = duration_value
    recognized["flexibility"] = flexibility_value
    return recognized


def _format_timing_ms(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}"
    return ""


def _format_pipeline_response(
    *,
    result,
    settings: Settings,
    mode: str | None,
    input_text: str,
    stt_source_override: str | None,
    transcript_log: list[dict[str, str]],
    total_override_ms: float | None = None,
):
    """Normalise pipeline output for API responses and CSV logging."""

    pipeline_metadata = (
        result.metadata if isinstance(result.metadata, Mapping) else {}
    )

    timings = dict(result.timings)
    existing_timing_payload = (
        pipeline_metadata.get("timings") if isinstance(pipeline_metadata, Mapping) else {}
    )
    if isinstance(existing_timing_payload, Mapping):
        timings.update(existing_timing_payload)
    if total_override_ms is not None:
        timings["totalMs"] = total_override_ms
    llm_network_ms = timings.get("llmNetworkMs")
    if isinstance(llm_network_ms, (int, float)):
        timings["llmNetworkMs"] = float(llm_network_ms)
    total_ms = timings.get("totalMs", 0.0)
    threshold_ms = settings.processing_threshold_ms
    threshold_breached = total_ms > threshold_ms
    timings["thresholdBreached"] = threshold_breached

    status = result.status
    error_detail = result.error

    data_payload: dict[str, object] = {}
    if result.normalized is not None and status != "error":
        data_payload = result.normalized.to_payload()
    elif status == "error" and error_detail:
        data_payload = {"error": error_detail}

    metadata: dict[str, object] = (
        {key: value for key, value in pipeline_metadata.items() if key != "timings"}
        if isinstance(pipeline_metadata, Mapping)
        else {}
    )
    metadata["mode"] = mode or settings.interaction_mode
    metadata["method"] = result.method_used
    metadata["requestedMethod"] = result.method_requested
    metadata["timings"] = timings
    metadata["validation"] = result.validation
    metadata["transcript"] = transcript_log

    if result.attempts:
        metadata["attempts"] = result.attempts

    extraction = result.extraction
    if extraction is not None:
        metadata["recognized"] = {
            "airports": getattr(extraction, "airports", []),
            "destinations": getattr(extraction, "destinations", []),
            "duration": getattr(extraction, "duration", None),
            "flexibility": getattr(extraction, "flexibility", None),
            "dates": [
                {"phrase": phrase, "iso": dt.isoformat()}
                for phrase, dt in getattr(extraction, "dates", [])
            ],
        }

    recognized_entities = _extract_recognized_entities(result)
    missing_fields = _derive_missing_fields(result)
    invalid_fields = _derive_invalid_fields(result)

    metadata["recognizedEntities"] = recognized_entities
    metadata["missingFields"] = missing_fields
    metadata["invalidFields"] = invalid_fields

    detection = result.detection
    if detection is not None:
        metadata["language"] = {
            "code": detection.language,
            "confidence": detection.confidence,
        }


    log_output: dict[str, object] = {
        "status": status,
        "data": data_payload,
        "validation": result.validation,
    }
    if status == "error" and error_detail:
        log_output["error"] = error_detail
    output_serialised = json.dumps(log_output, ensure_ascii=False)


    language_code = detection.language if detection is not None else ""
    language_confidence: object = getattr(detection, "confidence", "")
    language_metadata = metadata.get("language")
    if not language_code and isinstance(language_metadata, Mapping):
        language_code = str(language_metadata.get("code") or "")
        language_confidence = language_metadata.get("confidence", language_confidence)

    if isinstance(language_confidence, (int, float)):
        language_confidence_str = f"{float(language_confidence):.2f}"
    else:
        language_confidence_str = str(language_confidence) if language_confidence else ""




    def _pick_timing(*keys: str) -> float | None:
        for key in keys:
            value = timings.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    total_timing_value = _pick_timing("totalTimingMs", "totalMs", "total", "totalMilliseconds")
    if total_timing_value is None:
        total_timing_value = total_ms

    language_timing_value = _pick_timing("languageMs", "languageDetectionMs", "language")
    extraction_timing_value = _pick_timing("extractionMs", "extraction")
    mapping_timing_value = _pick_timing("normalizationMs", "normalisationMs", "mappingMs", "mapping")
    validation_timing_value = _pick_timing("validationMs", "validation")
    transcription_timing_value = _pick_timing("sttMs", "transcriptionMs", "voiceMs")
    network_latency_timing_value = _pick_timing("networkLatencyMs", "llmNetworkMs", "networkMs", "network")

    pipeline_status_display = status.capitalize() if isinstance(status, str) and status else ""
    method_value = str(result.method_used or metadata.get("method") or "")
    interaction_mode_value = str(metadata.get("mode") or "")
    request_type_value = "Voice" if stt_source_override else "Text"
    language_detection_summary = (
        f"{language_code} ({language_confidence_str})"
        if language_code and language_confidence_str
        else language_code or language_confidence_str
    )

    language_code = detection.language if detection is not None else ""
    language_confidence: object = getattr(detection, "confidence", "")
    language_metadata = metadata.get("language")
    if not language_code and isinstance(language_metadata, Mapping):
        language_code = str(language_metadata.get("code") or "")
        language_confidence = language_metadata.get("confidence", language_confidence)

    if isinstance(language_confidence, (int, float)):
        language_confidence_str = f"{float(language_confidence):.2f}"
    else:
        language_confidence_str = str(language_confidence) if language_confidence else ""

    llm_metadata = metadata.get("llm")
    if isinstance(llm_metadata, Mapping):
        llm_metadata = dict(llm_metadata)
    else:
        llm_metadata = {}
    metadata["llm"] = llm_metadata

    llm_provider = str(
        llm_metadata.get("provider")
        or llm_metadata.get("engine")
        or llm_metadata.get("model")
        or ""
    )

    prompt_payload: object = metadata.get("prompt")
    if not isinstance(prompt_payload, (Mapping, list)):
        prompt_payload = metadata.get("clarifications")
    if not isinstance(prompt_payload, (Mapping, list)):
        prompt_payload = None

    log_entry = {
        "Timestamp (UTC)": _utc_timestamp(),
        "User input": input_text,
        "Request type": request_type_value,
        "Method": method_value,
        "Interaction Mode": interaction_mode_value,
        "Pipeline Status": pipeline_status_display,
        "Language Detection": [
            _format_timing_ms(language_timing_value),
            language_detection_summary,
        ],
        "Processing Time": _format_timing_ms(total_timing_value),
        "Extraction": _format_timing_ms(extraction_timing_value),
        "Mapping": _format_timing_ms(mapping_timing_value),
        "Validation": _format_timing_ms(validation_timing_value),
        "Transcription": _format_timing_ms(transcription_timing_value),
        "Network Latency": _format_timing_ms(network_latency_timing_value),
        "Output": output_serialised,
    }

    return status, data_payload, metadata, log_entry, error_detail
def _prepare_import_requests(payload: ParseRequest) -> Iterable[ParseRequest]:
    if isinstance(payload.batch, str):
        raise HTTPException(
            status_code=400,
            detail="Batch storage references are not supported in this environment.",
        )
    if not payload.batch:
        raise HTTPException(
            status_code=400,
            detail="Import mode requires a non-empty batch payload.",
        )

    for item in payload.batch:
        yield ParseRequest(text=item.text, mode=item.mode, method=item.method)


def _summarise_import(
    summary: ImportSummaryData,
    *,
    mode: str | None,
    summary_logger: ImportSummaryLogger | None,
) -> ImportSummarySchema:
    response = build_import_summary(summary, mode=mode)

    if summary_logger is not None:
        summary_logger.log(response)

    return response


@api_router.post("/parse", response_model=ParseResponse | ImportSummarySchema)
async def parse_text(
    payload: ParseRequest,
    settings: Settings = Depends(get_settings),
    pipeline: HolidaySearchPipeline = Depends(get_pipeline),
    logger: CSVLogger = Depends(get_csv_logger),
    summary_logger: ImportSummaryLogger | None = Depends(get_import_summary_logger),
) -> ParseResponse | ImportSummarySchema:
    """Run the NLP pipeline and expose timings plus validation metadata."""

    if payload.import_mode:
        runner = ImportJobRunner(pipeline=pipeline, settings=settings, logger=None)
        try:
            summary = await runner.run_import(_prepare_import_requests(payload))
        except GuardrailOverloadError as exc:  # pragma: no cover - defensive
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
            ) from exc
        return _summarise_import(summary, mode=payload.mode, summary_logger=summary_logger)

    result = pipeline.run(payload.text, method=payload.method)

    transcript_log = [{"role": "user", "text": payload.text}]
    (
        pipeline_status,
        data_payload,
        metadata,
        log_entry,
        error_detail,
    ) = _format_pipeline_response(
        result=result,
        settings=settings,
        mode=payload.mode,
        input_text=payload.text,
        stt_source_override=None,
        transcript_log=transcript_log,
    )

    logger.log(log_entry)

    if pipeline_status == "error" and error_detail:
        raise HTTPException(status_code=400, detail=error_detail)

    return ParseResponse(status=pipeline_status, data=data_payload, metadata=metadata)


@api_router.post("/dialog", response_model=DialogResponse)
async def dialog_turn(
    payload: DialogRequest,
    settings: Settings = Depends(get_settings),
    orchestrator: DialogOrchestrator = Depends(get_dialog_orchestrator),
    logger: CSVLogger = Depends(get_csv_logger),
) -> DialogResponse:
    """Process a dialog turn, emitting clarification prompts when required."""

    outcome = orchestrator.handle_turn(
        payload.text,
        session_id=payload.session_id,
        mode=payload.mode,
        method=payload.method,
    )

    metadata = dict(outcome.metadata)
    timings = dict(metadata.get("timings", {}))
    total_ms_raw = timings.get("totalMs", 0.0)
    total_ms = float(total_ms_raw) if isinstance(total_ms_raw, (int, float)) else 0.0
    threshold_ms = settings.processing_threshold_ms
    threshold_breached = total_ms > threshold_ms
    timings["totalMs"] = total_ms
    timings["thresholdBreached"] = threshold_breached
    metadata["timings"] = timings
    metadata.setdefault("mode", payload.mode or settings.interaction_mode)
    metadata["rawStatus"] = outcome.raw_status
    metadata["status"] = outcome.status
    metadata["missingParameters"] = list(outcome.missing_parameters)

    prompt_payload = outcome.prompt.to_dict() if outcome.prompt else None

    log_output: dict[str, object] = {
        "status": outcome.status,
        "data": outcome.data,
        "validation": outcome.validation,
    }
    if outcome.error:
        log_output["error"] = outcome.error
    output_serialised = json.dumps(log_output, ensure_ascii=False)

    log_status: str
    if outcome.status == "success":
        log_status = "success"
    elif outcome.raw_status == "error":
        log_status = "error"
    else:
        log_status = "failed"

    language_payload = metadata.get("language")
    language_code = ""
    language_confidence: object = ""
    if isinstance(language_payload, Mapping):
        language_code = str(language_payload.get("code") or "")
        language_confidence = language_payload.get("confidence", "")
    if isinstance(language_confidence, (int, float)):
        language_confidence_str = f"{float(language_confidence):.2f}"
    else:
        language_confidence_str = str(language_confidence) if language_confidence else ""

    def _pick_timing(*keys: str) -> float | None:
        for key in keys:
            value = timings.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    total_timing_value = _pick_timing("totalTimingMs", "totalMs", "total", "totalMilliseconds")
    if total_timing_value is None:
        total_timing_value = total_ms

    language_timing_value = _pick_timing("languageMs", "languageDetectionMs", "language")
    extraction_timing_value = _pick_timing("extractionMs", "extraction")
    mapping_timing_value = _pick_timing("normalizationMs", "normalisationMs", "mappingMs", "mapping")
    validation_timing_value = _pick_timing("validationMs", "validation")
    transcription_timing_value = _pick_timing("sttMs", "transcriptionMs", "voiceMs")
    network_latency_timing_value = _pick_timing("networkLatencyMs", "llmNetworkMs", "networkMs", "network")

    language_detection_summary = (
        f"{language_code} ({language_confidence_str})"
        if language_code and language_confidence_str
        else language_code or language_confidence_str
    )
    pipeline_status_display = log_status.capitalize() if log_status else ""
    method_value = str(metadata.get("method") or "")
    interaction_mode_value = str(metadata.get("mode") or "")

    language_payload = metadata.get("language")
    language_code = ""
    language_confidence: object = ""
    if isinstance(language_payload, Mapping):
        language_code = str(language_payload.get("code") or "")
        language_confidence = language_payload.get("confidence", "")
    if isinstance(language_confidence, (int, float)):
        language_confidence_str = f"{float(language_confidence):.2f}"
    else:
        language_confidence_str = str(language_confidence) if language_confidence else ""

    llm_metadata = metadata.get("llm")
    if isinstance(llm_metadata, Mapping):
        llm_metadata = dict(llm_metadata)
    else:
        llm_metadata = {}
    metadata["llm"] = llm_metadata

    llm_provider = str(
        llm_metadata.get("provider")
        or llm_metadata.get("engine")
        or llm_metadata.get("model")
        or ""
    )

    log_entry = {
        "Timestamp (UTC)": _utc_timestamp(),
        "User input": payload.text,
        "Request type": "Text",
        "Method": method_value,
        "Interaction Mode": interaction_mode_value,
        "Pipeline Status": pipeline_status_display,
        "Language Detection": [
            _format_timing_ms(language_timing_value),
            language_detection_summary,
        ],
        "Processing Time": _format_timing_ms(total_timing_value),
        "Extraction": _format_timing_ms(extraction_timing_value),
        "Mapping": _format_timing_ms(mapping_timing_value),
        "Validation": _format_timing_ms(validation_timing_value),
        "Transcription": _format_timing_ms(transcription_timing_value),
        "Network Latency": _format_timing_ms(network_latency_timing_value),
        "Output": output_serialised,
    }
    logger.log(log_entry)

    if outcome.status == "failed" and outcome.error:
        raise HTTPException(status_code=400, detail=outcome.error)

    response_prompt = prompt_payload if prompt_payload is None else ClarificationPayload(**prompt_payload)
    return DialogResponse(
        status=outcome.status,
        session_id=outcome.session_id,
        data=outcome.data,
        prompt=response_prompt,
        metadata=metadata,
    )


@api_router.get("/fixtures")
async def fetch_fixtures(
    pipeline: HolidaySearchPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Expose fixture content to assist the frontend with UI hints."""

    repo = pipeline.fixtures
    config = pipeline.configuration
    methods_catalog = pipeline.methods_catalog

    airports = repo.list_airports()
    destinations = repo.list_destinations()
    dates = repo.list_checkin_dates()

    configuration = {
        "defaults": config.defaults,
        "roomsConfiguration": config.rooms_configuration,
        "durationOptions": config.durations,
        "flexibility": config.flexibility,
    }

    requested_alias = settings.llm_method
    resolved_default = methods_catalog.lookup(requested_alias) or methods_catalog.default_method

    return {
        "airports": airports,
        "destinations": destinations,
        "dates": dates,
        "configuration": configuration,
        "voiceEnabled": settings.voice_enabled,
        "showFailedOnly": settings.show_failed_only,
        "mode": settings.interaction_mode,
        "llmMethod": resolved_default.id,
        "llmMethodAlias": requested_alias,
        "availableMethods": methods_catalog.to_metadata(),
        "defaultMethod": methods_catalog.default_method_id,
        "methodDefaults": dict(methods_catalog.defaults),
        "performanceTargets": {
            "importP95ThresholdMs": settings.import_p95_threshold_ms,
            "importP95SampleSize": settings.import_p95_sample_size,
            "importP95Significance": settings.import_p95_significance,
        },
        "suggestionsEnabled": settings.suggestions_enabled,
        "suggestionsLimit": _resolve_suggestions_limit(settings),
    }


@api_router.get("/suggestions")
async def fetch_suggestions(
    q: str,
    limit: int = 3,
    settings: Settings = Depends(get_settings),
    service: AutoCompletionService = Depends(get_auto_completion_service),
) -> dict[str, object]:
    """Return auto-completion suggestions derived from popularity statistics."""

    if not settings.suggestions_enabled:
        return {"suggestions": {}}

    normalized_query = (q or "").strip()
    if not normalized_query:
        return {"suggestions": {}}

    configured_limit = _resolve_suggestions_limit(settings)
    requested_limit = max(1, int(limit or 1))
    safe_limit = min(requested_limit, configured_limit)

    resolved_service = cast(AutoCompletionService, _resolve_dependency(service))
    suggestions = resolved_service.suggest(normalized_query, safe_limit)
    return {"suggestions": suggestions}


@api_router.post("/voice", response_model=VoiceResponse)
async def voice_endpoint(
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    pipeline: HolidaySearchPipeline = Depends(get_pipeline),
    logger: CSVLogger = Depends(get_csv_logger),
    stt_client: SpeechToTextClient | None = Depends(get_stt_client),
) -> VoiceResponse:
    """Transcribe an audio sample and feed it through the holiday search pipeline."""

    pipeline = cast(HolidaySearchPipeline, _resolve_dependency(pipeline))
    logger = cast(CSVLogger, _resolve_dependency(logger))
    resolved_stt_client = _resolve_dependency(stt_client)
    stt_client = cast(SpeechToTextClient | None, resolved_stt_client)

    total_start = perf_counter()

    if not settings.voice_enabled:
        await audio.close()
        metadata = {
            "timings": {"totalMs": (perf_counter() - total_start) * 1000},
            "mode": settings.interaction_mode,
        }
        return VoiceResponse(
            status="noop",
            voice_enabled=False,
            engine=None,
            transcript=None,
            words=[],
            data=None,
            metadata=metadata,
        )

    if stt_client is None:
        # ``get_stt_client`` already swaps in the local faster-whisper fallback when
        # Deepgram credentials are absent, so reaching this branch means no speech
        # engine could be initialised at all.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Speech-to-text provider is not configured",
        )

    raw_content_type = (audio.content_type or "").lower()
    base_content_type = raw_content_type.split(";")[0].strip() or raw_content_type

    sniff_leading_bytes = b""
    if not base_content_type or base_content_type == "application/octet-stream":
        (
            raw_content_type,
            base_content_type,
            sniff_leading_bytes,
        ) = await _resolve_missing_audio_content_type(audio, raw_content_type, base_content_type)

    allowed_types = {item.lower() for item in settings.voice_allowed_content_types}
    if base_content_type not in allowed_types:
        await audio.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported audio format",
        )

    file_obj = getattr(audio, "file", None)
    if file_obj is not None:
        try:
            current_pos = file_obj.tell()
        except (OSError, AttributeError):
            current_pos = None
        try:
            file_obj.seek(0, 2)
            size = file_obj.tell()
        except (OSError, AttributeError):
            size = None
        finally:
            try:
                if current_pos is None:
                    file_obj.seek(0)
                else:
                    file_obj.seek(current_pos)
            except (OSError, AttributeError):
                pass
        if size is not None and size > settings.voice_max_bytes:
            await audio.close()
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Audio payload exceeds maximum allowed size",
            )

    try:
        await audio.seek(0)
    except (AttributeError, TypeError, OSError):
        pass

    class _AudioTooLargeError(Exception):
        """Raised when the streamed payload exceeds the configured limit."""

    async def audio_stream() -> AsyncIterator[bytes]:
        remaining = settings.voice_max_bytes
        pending = sniff_leading_bytes
        try:
            if pending:
                remaining -= len(pending)
                if remaining < 0:
                    raise _AudioTooLargeError
                yield pending
                pending = b""
            while True:
                chunk = await audio.read(8192)
                if not chunk:
                    break
                remaining -= len(chunk)
                if remaining < 0:
                    raise _AudioTooLargeError
                yield chunk
        finally:
            await audio.close()

    stt_start_ns = perf_counter_ns()
    try:
        transcription: TranscriptionResult = await stt_client.transcribe(
            content_type=raw_content_type or base_content_type,
            stream=audio_stream(),
        )
    except _AudioTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Audio payload exceeds maximum allowed size",
        ) from exc
    except SpeechToTextError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    elapsed_ns = perf_counter_ns() - stt_start_ns
    # Round up to the nearest microsecond expressed in milliseconds so that we do not
    # under-report short durations due to floating point truncation.
    stt_ms = (elapsed_ns + 999) // 1_000
    stt_ms /= 1000

    if transcription.words:
        starts = [item.start for item in transcription.words]
        ends = [item.end for item in transcription.words]
        if starts and ends:
            min_start = min(starts)
            max_end = max(ends)
            if max_end >= min_start:
                word_span_ms = (max_end - min_start) * 1000
                stt_ms = max(stt_ms, word_span_ms)

    transcript_text = transcription.text.strip()
    if not transcript_text:
        raise HTTPException(status_code=422, detail="No speech detected in audio sample")

    pipeline_result = pipeline.run(transcript_text)
    pipeline_total_ms = pipeline_result.timings.get("totalMs", 0.0)
    combined_total_ms = pipeline_total_ms + stt_ms

    transcript_log = [{"role": "user", "text": transcript_text}]
    status_value, data_payload, metadata, log_entry, error_detail = _format_pipeline_response(
        result=pipeline_result,
        settings=settings,
        mode=None,
        input_text=transcript_text,
        stt_source_override=settings.stt_engine,
        transcript_log=transcript_log,
        total_override_ms=combined_total_ms,
    )

    timings = dict(metadata.get("timings", {}))
    timings.setdefault("pipelineTotalMs", pipeline_total_ms)
    timings["sttMs"] = stt_ms
    metadata["timings"] = timings

    logger.log(log_entry)

    if status_value == "error" and error_detail:
        raise HTTPException(status_code=400, detail=error_detail)

    word_timings = [
        VoiceWordTiming(word=item.word, start=item.start, end=item.end)
        for item in transcription.words
    ]

    return VoiceResponse(
        status=status_value,
        voice_enabled=True,
        engine=settings.stt_engine,
        transcript=transcript_text,
        words=word_timings,
        data=data_payload,
        metadata=metadata,
    )


__all__ = ["api_router"]
