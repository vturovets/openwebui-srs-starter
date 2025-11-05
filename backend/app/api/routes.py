"""Versioned API route definitions for the OpenWebUI SRS backend."""

from __future__ import annotations

import json
from time import perf_counter

from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..dependencies import (
    get_csv_logger,
    get_dialog_orchestrator,
    get_stt_client,
    get_pipeline,
    get_settings,
)
from ..logging.csv_logger import CSVLogger
from ..pipeline.dialog import DialogOrchestrator
from ..pipeline.pipeline import HolidaySearchPipeline
from ..integrations.stt import (
    SpeechToTextClient,
    SpeechToTextError,
    TranscriptionResult,
)

api_router = APIRouter(prefix="/v1", tags=["v1"])


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

    timings = dict(result.timings)
    if total_override_ms is not None:
        timings["totalMs"] = total_override_ms
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

    metadata: dict[str, object] = {
        "mode": mode or settings.interaction_mode,
        "method": result.method_used,
        "requestedMethod": result.method_requested,
        "timings": timings,
        "validation": result.validation,
        "transcript": transcript_log,
    }

    if result.metadata.get("hybrid"):
        metadata["hybrid"] = result.metadata["hybrid"]
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

    detection = result.detection
    if detection is not None:
        metadata["language"] = {
            "code": detection.language,
            "confidence": detection.confidence,
        }

    stt_source = (
        stt_source_override
        if stt_source_override
        else (settings.stt_engine or ("voice" if settings.voice_enabled else "text"))
    )

    log_output: dict[str, object] = {
        "status": status,
        "data": data_payload,
        "validation": result.validation,
    }
    if status == "error" and error_detail:
        log_output["error"] = error_detail
    output_serialised = json.dumps(log_output, ensure_ascii=False)

    log_entry = {
        "Timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "Input": input_text,
        "Language": detection.language if detection is not None else "",
        "Method": result.method_used,
        "STT": stt_source or "",
        "ProcessingTime": f"{total_ms:.2f}",
        "Output": output_serialised,
        "Status": status,
        "ThresholdBreached": "true" if threshold_breached else "false",
        "SessionId": "",
        "DialogStatus": metadata["mode"],
        "MissingParameters": "",
        "Prompt": "",
        "Transcript": json.dumps(transcript_log, ensure_ascii=False),
    }

    return status, data_payload, metadata, log_entry, error_detail
@api_router.post("/parse", response_model=ParseResponse)
async def parse_text(
    payload: ParseRequest,
    settings: Settings = Depends(get_settings),
    pipeline: HolidaySearchPipeline = Depends(get_pipeline),
    logger: CSVLogger = Depends(get_csv_logger),
) -> ParseResponse:
    """Run the NLP pipeline and expose timings plus validation metadata."""

    result = pipeline.run(payload.text, method=payload.method)

    transcript_log = [{"role": "user", "text": payload.text}]
    status, data_payload, metadata, log_entry, error_detail = _format_pipeline_response(
        result=result,
        settings=settings,
        mode=payload.mode,
        input_text=payload.text,
        stt_source_override=None,
        transcript_log=transcript_log,
    )

    logger.log(log_entry)

    if status == "error" and error_detail:
        raise HTTPException(status_code=400, detail=error_detail)

    return ParseResponse(status=status, data=data_payload, metadata=metadata)


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

    stt_source = settings.stt_engine if settings.stt_engine else ("voice" if settings.voice_enabled else "text")

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

    transcript_serialised = json.dumps(outcome.transcript, ensure_ascii=False)
    missing_serialised = (
        json.dumps(outcome.missing_parameters, ensure_ascii=False)
        if outcome.missing_parameters
        else ""
    )
    prompt_serialised = json.dumps(prompt_payload, ensure_ascii=False) if prompt_payload else ""

    log_entry = {
        "Timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "Input": payload.text,
        "Language": metadata.get("language", {}).get("code", ""),
        "Method": metadata.get("method", ""),
        "STT": stt_source or "",
        "ProcessingTime": f"{total_ms:.2f}",
        "Output": output_serialised,
        "Status": log_status,
        "ThresholdBreached": "true" if threshold_breached else "false",
        "SessionId": outcome.session_id or "",
        "DialogStatus": outcome.status,
        "MissingParameters": missing_serialised,
        "Prompt": prompt_serialised,
        "Transcript": transcript_serialised,
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
async def fetch_fixtures(pipeline: HolidaySearchPipeline = Depends(get_pipeline)) -> dict[str, object]:
    """Expose fixture content to assist the frontend with UI hints."""

    repo = pipeline.fixtures
    config = pipeline.configuration

    airports = repo.list_airports()
    destinations = repo.list_destinations()
    dates = repo.list_checkin_dates()

    configuration = {
        "defaults": config.defaults,
        "roomsConfiguration": config.rooms_configuration,
        "durationOptions": config.durations,
        "flexibility": config.flexibility,
    }

    return {
        "airports": airports,
        "destinations": destinations,
        "dates": dates,
        "configuration": configuration,
    }


@api_router.post("/voice", response_model=VoiceResponse)
async def voice_endpoint(
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    pipeline: HolidaySearchPipeline = Depends(get_pipeline),
    logger: CSVLogger = Depends(get_csv_logger),
    stt_client: SpeechToTextClient | None = Depends(get_stt_client),
) -> VoiceResponse:
    """Transcribe an audio sample and feed it through the holiday search pipeline."""

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Speech-to-text provider is not configured",
        )

    content_type = (audio.content_type or "").lower()
    allowed_types = {item.lower() for item in settings.voice_allowed_content_types}
    if content_type not in allowed_types:
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
    except (AttributeError, TypeError):
        pass

    class _AudioTooLargeError(Exception):
        """Raised when the streamed payload exceeds the configured limit."""

    async def audio_stream() -> AsyncIterator[bytes]:
        remaining = settings.voice_max_bytes
        try:
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

    stt_start = perf_counter()
    try:
        transcription: TranscriptionResult = await stt_client.transcribe(
            content_type=content_type,
            stream=audio_stream(),
        )
    except _AudioTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Audio payload exceeds maximum allowed size",
        ) from exc
    except SpeechToTextError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    stt_ms = (perf_counter() - stt_start) * 1000

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
