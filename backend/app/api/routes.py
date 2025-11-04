"""Versioned API route definitions for the OpenWebUI SRS backend."""

from __future__ import annotations

from time import perf_counter

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import Settings
from ..dependencies import get_csv_logger, get_pipeline, get_settings
from ..logging.csv_logger import CSVLogger
from ..pipeline.pipeline import HolidaySearchPipeline
from ..pipeline.validator import ValidationError

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


class VoiceResponse(BaseModel):
    """Structured response for the voice endpoint."""

    status: str
    voice_enabled: bool
    engine: str | None
    metadata: dict[str, object]


class ParseResponse(BaseModel):
    """Structured response returned by the parse endpoint."""

    status: str
    data: dict[str, object]
    metadata: dict[str, object]


def _measure(label: str, timings: dict[str, float], func):
    start = perf_counter()
    try:
        return func()
    finally:
        timings[label] = (perf_counter() - start) * 1000


@api_router.post("/parse", response_model=ParseResponse)
async def parse_text(
    payload: ParseRequest,
    settings: Settings = Depends(get_settings),
    pipeline: HolidaySearchPipeline = Depends(get_pipeline),
    logger: CSVLogger = Depends(get_csv_logger),
) -> ParseResponse:
    """Run the NLP pipeline and expose timings plus validation metadata."""

    total_start = perf_counter()
    timings: dict[str, float] = {}

    detection = None
    extraction = None
    normalized = None
    validation_meta: dict[str, object] = {"status": "passed", "errors": []}
    status = "success"
    error_detail: str | None = None
    http_error: HTTPException | None = None

    try:
        detection = _measure(
            "languageMs",
            timings,
            lambda: pipeline.language_detector.detect(payload.text),
        )
        extraction = _measure(
            "extractionMs",
            timings,
            lambda: pipeline.extractor.extract(payload.text),
        )
        normalized = _measure(
            "normalizationMs",
            timings,
            lambda: pipeline.normalizer.normalize(detection.language, extraction),
        )
        _measure("validationMs", timings, lambda: pipeline.validator.validate(normalized))
    except ValidationError as exc:  # validation failures are reported as successful HTTP responses
        status = "failed"
        validation_meta = {
            "status": "failed",
            "errors": [
                {
                    "message": str(exc),
                }
            ],
        }
    except ValueError as exc:
        error_detail = str(exc)
        status = "error"
        validation_meta = {
            "status": "error",
            "errors": [
                {
                    "message": error_detail,
                }
            ],
        }
        http_error = HTTPException(status_code=400, detail=error_detail)

    total_ms = (perf_counter() - total_start) * 1000
    timings["totalMs"] = total_ms
    threshold_ms = settings.processing_threshold_ms
    threshold_breached = total_ms > threshold_ms
    timings["thresholdBreached"] = threshold_breached

    data_payload: dict[str, object] = {}
    if normalized is not None and status != "error":
        data_payload = normalized.to_payload()
    elif status == "error" and error_detail:
        data_payload = {"error": error_detail}

    metadata: dict[str, object] = {
        "mode": payload.mode or settings.interaction_mode,
        "method": payload.method or settings.llm_method,
        "timings": timings,
        "validation": validation_meta,
    }

    if extraction is not None:
        metadata["recognized"] = {
            "airports": extraction.airports,
            "destinations": extraction.destinations,
            "duration": extraction.duration,
            "flexibility": extraction.flexibility,
            "dates": [
                {"phrase": phrase, "iso": dt.isoformat()} for phrase, dt in extraction.dates
            ],
        }

    if detection is not None:
        metadata["language"] = {
            "code": detection.language,
            "confidence": detection.confidence,
        }

    stt_source = settings.stt_engine if settings.stt_engine else ("voice" if settings.voice_enabled else "text")
    log_entry = {
        "Timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "Input": payload.text,
        "Language": detection.language if detection is not None else "",
        "Method": metadata["method"],
        "STT": stt_source or "",
        "ProcessingTime": f"{total_ms:.2f}",
        "Output": data_payload,
        "Status": f"{status}|threshold" if threshold_breached else status,
    }
    logger.log(log_entry)

    if http_error is not None:
        raise http_error

    return ParseResponse(status=status, data=data_payload, metadata=metadata)


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
async def voice_stub(settings: Settings = Depends(get_settings)) -> VoiceResponse:
    """Stub endpoint that mirrors voice-processing metadata."""

    timings: dict[str, float] = {}
    total_start = perf_counter()

    voice_enabled = settings.voice_enabled
    engine = settings.stt_engine if voice_enabled else None

    timings["totalMs"] = (perf_counter() - total_start) * 1000

    metadata = {
        "timings": timings,
        "mode": settings.interaction_mode,
    }

    status = "success" if voice_enabled else "noop"

    return VoiceResponse(
        status=status,
        voice_enabled=voice_enabled,
        engine=engine,
        metadata=metadata,
    )


__all__ = ["api_router"]
