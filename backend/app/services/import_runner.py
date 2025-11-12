"""Utilities to orchestrate bulk import jobs via the parsing pipeline."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping

from ..api.routes import ParseRequest, _format_pipeline_response
from ..config import Settings
from ..logging.csv_logger import CSVLogger
from ..pipeline.pipeline import HolidaySearchPipeline

SummaryCallback = Callable[["ImportSummary"], Awaitable[None] | None]


def _read_cpu_percent() -> float | None:
    """Estimate CPU utilisation percentage using the 1-minute load average."""

    try:
        load_1, _load_5, _load_15 = os.getloadavg()
    except (AttributeError, OSError):
        return None
    cpu_count = os.cpu_count() or 1
    if cpu_count <= 0:
        cpu_count = 1
    utilisation = (load_1 / cpu_count) * 100.0
    return max(utilisation, 0.0)


def _read_memory_usage_mb() -> float | None:
    """Approximate RAM usage by parsing ``/proc/meminfo`` when available."""

    meminfo_path = "/proc/meminfo"
    try:
        with open(meminfo_path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except (FileNotFoundError, OSError):
        return None

    total_kb = available_kb = None
    for line in lines:
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2:
                total_kb = float(parts[1])
        elif line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2:
                available_kb = float(parts[1])
        if total_kb is not None and available_kb is not None:
            break

    if total_kb is None or available_kb is None:
        return None
    used_kb = max(total_kb - available_kb, 0.0)
    return used_kb / 1024.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_total_ms(timings: Mapping[str, Any] | None) -> float:
    if not isinstance(timings, Mapping):
        return 0.0
    candidates = (
        "totalMs",
        "totalTimingMs",
        "totalMilliseconds",
        "total",
    )
    for key in candidates:
        value = timings.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _ensure_timings(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if isinstance(metadata, Mapping):
        timings = metadata.get("timings")
        if isinstance(timings, Mapping):
            return timings
    return {}


LatencyHistogram = dict[str, int]

DEFAULT_LATENCY_BUCKETS: tuple[tuple[float, float | None], ...] = (
    (0.0, 100.0),
    (100.0, 250.0),
    (250.0, 500.0),
    (500.0, 1000.0),
    (1000.0, 2000.0),
    (2000.0, 5000.0),
    (5000.0, None),
)


def _bucket_label(lower: float, upper: float | None) -> str:
    lower_display = int(lower)
    if upper is None:
        return f"{lower_display}ms+"
    upper_display = int(upper) - 1
    return f"{lower_display}-{upper_display}ms"


LATENCY_BUCKET_LABELS: tuple[str, ...] = tuple(
    _bucket_label(lower, upper) for lower, upper in DEFAULT_LATENCY_BUCKETS
)


def _initial_histogram() -> LatencyHistogram:
    return {label: 0 for label in LATENCY_BUCKET_LABELS}


@dataclass(slots=True)
class JobMetrics:
    """Aggregated metrics for an import job."""

    total_requests: int
    success_count: int
    failed_count: int
    error_count: int
    latency_histogram: LatencyHistogram = field(default_factory=_initial_histogram)
    peak_concurrency: int = 0

    @property
    def status_counts(self) -> Mapping[str, int]:
        return {
            "success": self.success_count,
            "failed": self.failed_count,
            "error": self.error_count,
        }


@dataclass(slots=True)
class ImportSummary:
    """Summary emitted once an import job has finished processing."""

    metrics: JobMetrics
    started_at: datetime
    finished_at: datetime
    duration_ms: float


class ImportJobRunner:
    """Run batches of parse requests with bounded concurrency."""

    def __init__(
        self,
        *,
        pipeline: HolidaySearchPipeline,
        settings: Settings,
        logger: CSVLogger | None = None,
        concurrency_limit: int | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._settings = settings
        self._logger = logger
        requested = concurrency_limit or settings.import_worker_concurrency
        self._requested_concurrency = max(1, requested)

    async def run_import(
        self,
        payloads: Iterable[ParseRequest] | AsyncIterable[ParseRequest],
        *,
        summary_callback: SummaryCallback | None = None,
    ) -> ImportSummary:
        runtime_controls = configure_import_runtime(
            self._settings, concurrency_override=self._requested_concurrency
        )
        semaphore = runtime_controls.semaphore
        concurrency_lock = asyncio.Lock()
        metrics_lock = asyncio.Lock()

        metrics_state = {
            "total_requests": 0,
            "success_count": 0,
            "failed_count": 0,
            "error_count": 0,
            "latency_histogram": _initial_histogram(),
            "peak_concurrency": 0,
        }

        current_concurrency = 0

        async def _record_metrics(status: str, total_ms: float) -> None:
            nonlocal metrics_state
            bucket = LATENCY_BUCKET_LABELS[-1]
            for (lower, upper), label in zip(DEFAULT_LATENCY_BUCKETS, LATENCY_BUCKET_LABELS):
                if upper is None or total_ms < upper:
                    bucket = label
                    break
            async with metrics_lock:
                metrics_state["total_requests"] += 1
                if status == "success":
                    metrics_state["success_count"] += 1
                elif status == "failed":
                    metrics_state["failed_count"] += 1
                else:
                    metrics_state["error_count"] += 1
                metrics_state["latency_histogram"][bucket] += 1

        async def _process_payload(payload: ParseRequest) -> None:
            nonlocal current_concurrency
            async with semaphore:
                async with concurrency_lock:
                    current_concurrency += 1
                    metrics_state["peak_concurrency"] = max(
                        metrics_state["peak_concurrency"], current_concurrency
                    )
                try:
                    result = await asyncio.to_thread(
                        self._pipeline.run,
                        payload.text,
                        method=payload.method,
                    )
                    transcript_log = [{"role": "user", "text": payload.text}]
                    (
                        status,
                        _data_payload,
                        metadata,
                        log_entry,
                        error_detail,
                    ) = _format_pipeline_response(
                        result=result,
                        settings=self._settings,
                        mode=payload.mode,
                        input_text=payload.text,
                        stt_source_override=None,
                        transcript_log=transcript_log,
                    )
                    if self._logger is not None:
                        await asyncio.to_thread(self._logger.log, log_entry)
                    timings = _ensure_timings(metadata)
                    total_ms = _coerce_total_ms(timings)
                    await _record_metrics(status, total_ms)
                    if status == "error" and error_detail:
                        # Pipeline errors are captured in the aggregate metrics
                        return
                except Exception:
                    await _record_metrics("error", 0.0)
                finally:
                    async with concurrency_lock:
                        current_concurrency -= 1

        tasks: list[asyncio.Task[None]] = []

        async def _iterate() -> AsyncIterable[ParseRequest]:
            if isinstance(payloads, AsyncIterable):
                async for item in payloads:
                    yield item
            else:
                for item in payloads:
                    yield item

        started_at = _now_utc()
        start_time = perf_counter()
        async for request in _iterate():
            await runtime_controls.wait_for_capacity()
            tasks.append(asyncio.create_task(_process_payload(request)))
            if len(tasks) >= runtime_controls.batch_size:
                await asyncio.gather(*tasks)
                tasks.clear()

        if tasks:
            await asyncio.gather(*tasks)

        finished_at = _now_utc()
        duration_ms = (perf_counter() - start_time) * 1000

        summary = ImportSummary(
            metrics=JobMetrics(
                total_requests=metrics_state["total_requests"],
                success_count=metrics_state["success_count"],
                failed_count=metrics_state["failed_count"],
                error_count=metrics_state["error_count"],
                latency_histogram=dict(metrics_state["latency_histogram"]),
                peak_concurrency=metrics_state["peak_concurrency"],
            ),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

        if summary_callback is not None:
            maybe_coro = summary_callback(summary)
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro

        return summary

@dataclass(slots=True)
class ImportRuntimeControls:
    """Runtime orchestration parameters for import execution."""

    semaphore: asyncio.Semaphore
    batch_size: int
    pause_seconds: float
    cpu_threshold: float | None
    memory_threshold_mb: float | None

    async def wait_for_capacity(self) -> None:
        """Sleep when system load exceeds configured thresholds."""

        if self.cpu_threshold is None and self.memory_threshold_mb is None:
            return

        while True:
            throttle = False
            if self.cpu_threshold is not None:
                cpu_percent = _read_cpu_percent()
                if cpu_percent is not None and cpu_percent >= self.cpu_threshold:
                    throttle = True
            if self.memory_threshold_mb is not None:
                memory_mb = _read_memory_usage_mb()
                if memory_mb is not None and memory_mb >= self.memory_threshold_mb:
                    throttle = True
            if throttle:
                await asyncio.sleep(self.pause_seconds)
                continue
            break


def configure_import_runtime(
    settings: Settings,
    *,
    concurrency_override: int | None = None,
) -> ImportRuntimeControls:
    """Resolve runtime knobs for import execution using application settings."""

    requested = concurrency_override or settings.import_worker_concurrency
    concurrency_limit = max(1, min(requested, settings.import_max_concurrency))
    semaphore = asyncio.Semaphore(concurrency_limit)
    batch_size = max(1, settings.import_batch_size)
    pause_seconds = settings.import_pause_seconds
    cpu_threshold = settings.import_cpu_threshold
    memory_threshold = settings.import_memory_threshold_mb

    return ImportRuntimeControls(
        semaphore=semaphore,
        batch_size=batch_size,
        pause_seconds=pause_seconds,
        cpu_threshold=cpu_threshold,
        memory_threshold_mb=memory_threshold,
    )
