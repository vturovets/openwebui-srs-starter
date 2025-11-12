"""Utilities to orchestrate bulk import jobs via the parsing pipeline."""

from __future__ import annotations

import asyncio
import math
from builtins import anext
from collections import deque
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping, Sequence

from ..config import Settings
from ..logging.csv_logger import CSVLogger
from ..pipeline.pipeline import HolidaySearchPipeline
from ..telemetry.resource_monitor import ResourceMonitor
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..api.routes import ParseRequest

SummaryCallback = Callable[["ImportSummary"], Awaitable[None] | None]
ProgressCallback = Callable[["ImportProgress"], Awaitable[None] | None]


class GuardrailOverloadError(RuntimeError):
    """Raised when guardrail thresholds continuously reject new work."""


def _calculate_percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return math.nan
    if len(values) == 1:
        return float(values[0])
    position = percentile * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[int(position)])
    fraction = position - lower
    lower_value = float(values[lower])
    upper_value = float(values[upper])
    return lower_value + (upper_value - lower_value) * fraction


def _calculate_percentiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p90": None, "p95": None, "p99": None}
    sorted_values = sorted(values)
    percentiles = {
        "p50": _calculate_percentile(sorted_values, 0.50),
        "p90": _calculate_percentile(sorted_values, 0.90),
        "p95": _calculate_percentile(sorted_values, 0.95),
        "p99": _calculate_percentile(sorted_values, 0.99),
    }
    return percentiles


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
    retry_count: int = 0
    permanent_failures: int = 0

    @property
    def status_counts(self) -> Mapping[str, int]:
        return {
            "success": self.success_count,
            "failed": self.failed_count,
            "error": self.error_count,
        }

    @property
    def retryCount(self) -> int:
        return self.retry_count

    @property
    def permanentFailures(self) -> int:
        return self.permanent_failures


@dataclass(slots=True)
class ImportSummary:
    """Summary emitted once an import job has finished processing."""

    metrics: JobMetrics
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    total_processing_ms: float
    latency_percentiles: Mapping[str, float | None]
    cpu_samples: list[float]
    memory_samples: list[float]
    guardrail_actions: list["GuardrailAction"]
    peakCpu: float | None = None
    peakMemoryMb: float | None = None
    throttleCount: int = 0

    @property
    def retryCount(self) -> int:
        return self.metrics.retry_count

    @property
    def permanentFailures(self) -> int:
        return self.metrics.permanent_failures


@dataclass(slots=True)
class GuardrailAction:
    """Representation of a guardrail action applied during import execution."""

    type: str
    count: int


@dataclass(slots=True, frozen=True)
class ImportProgress:
    """Snapshot of import execution progress."""

    processed: int
    status_counts: Mapping[str, int]
    total: int | None = None


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
        progress_callback: ProgressCallback | None = None,
        total: int | None = None,
    ) -> ImportSummary:
        from ..api import routes as api_routes

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
            "durations": [],
            "retry_count": 0,
            "permanent_failures": 0,
        }

        current_concurrency = 0

        async def _record_metrics(status: str, total_ms: float) -> None:
            nonlocal metrics_state
            bucket = LATENCY_BUCKET_LABELS[-1]
            for (lower, upper), label in zip(DEFAULT_LATENCY_BUCKETS, LATENCY_BUCKET_LABELS):
                if upper is None or total_ms < upper:
                    bucket = label
                    break
            progress_update: ImportProgress | None = None
            async with metrics_lock:
                metrics_state["total_requests"] += 1
                if status == "success":
                    metrics_state["success_count"] += 1
                elif status == "failed":
                    metrics_state["failed_count"] += 1
                else:
                    metrics_state["error_count"] += 1
                metrics_state["latency_histogram"][bucket] += 1
                metrics_state["durations"].append(total_ms)
                if progress_callback is not None:
                    progress_update = ImportProgress(
                        processed=metrics_state["total_requests"],
                        status_counts={
                            "success": metrics_state["success_count"],
                            "failed": metrics_state["failed_count"],
                            "error": metrics_state["error_count"],
                        },
                        total=total,
                    )
            if progress_update is not None and progress_callback is not None:
                maybe_coro = progress_callback(progress_update)
                if asyncio.iscoroutine(maybe_coro):
                    await maybe_coro

        async def _process_payload(payload: ParseRequest) -> None:
            nonlocal current_concurrency
            async with semaphore:
                async with concurrency_lock:
                    current_concurrency += 1
                    metrics_state["peak_concurrency"] = max(
                        metrics_state["peak_concurrency"], current_concurrency
                    )
                try:
                    max_attempts = max(1, int(self._settings.import_retry_attempts))
                    backoff_base = max(0.0, float(self._settings.import_retry_backoff_seconds))
                except Exception:  # pragma: no cover - defensive conversion
                    max_attempts = 1
                    backoff_base = 0.0

                attempt = 0
                try:
                    while True:
                        attempt += 1
                        status = "error"
                        metadata: Mapping[str, Any] | None = None
                        log_entry: Mapping[str, Any] | None = None
                        error_detail: str | None = None
                        total_ms = 0.0
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
                            ) = api_routes._format_pipeline_response(
                                result=result,
                                settings=self._settings,
                                mode=payload.mode,
                                input_text=payload.text,
                                stt_source_override=None,
                                transcript_log=transcript_log,
                            )
                            timings = _ensure_timings(metadata)
                            total_ms = _coerce_total_ms(timings)
                        except Exception:
                            metadata = None
                            log_entry = None
                            error_detail = "exception"

                        is_transient = status == "error"
                        should_retry = is_transient and attempt < max_attempts
                        if should_retry:
                            metrics_state["retry_count"] += 1
                            sleep_for = backoff_base * (2 ** (attempt - 1))
                            if sleep_for > 0:
                                await asyncio.sleep(sleep_for)
                            continue

                        final_status = status if status in {"success", "failed"} else "error"
                        if is_transient and final_status == "error":
                            metrics_state["permanent_failures"] += 1

                        if self._logger is not None and log_entry is not None:
                            await asyncio.to_thread(self._logger.log, log_entry)

                        await _record_metrics(final_status, total_ms)
                        if final_status == "error" and error_detail:
                            return
                        break
                finally:
                    async with concurrency_lock:
                        current_concurrency -= 1

        tasks: list[asyncio.Task[None]] = []
        pending_requests: deque[ParseRequest] = deque()

        async def _iterate() -> AsyncIterable[ParseRequest]:
            if isinstance(payloads, AsyncIterable):
                async for item in payloads:
                    yield item
            else:
                for item in payloads:
                    yield item

        sample_interval = max(0.01, float(self._settings.import_pause_seconds or 0.0))

        async with ResourceMonitor(
            interval=sample_interval,
            cpu_threshold=runtime_controls.cpu_threshold,
            memory_threshold_mb=runtime_controls.memory_threshold_mb,
        ) as monitor:
            started_at = _now_utc()
            start_time = perf_counter()
            last_counter: int | None = None
            iterator = _iterate().__aiter__()
            producer_exhausted = False

            while not producer_exhausted or pending_requests:
                if not producer_exhausted:
                    try:
                        request = await anext(iterator)
                        pending_requests.append(request)
                    except StopAsyncIteration:
                        producer_exhausted = True

                while pending_requests:
                    last_counter = await runtime_controls.wait_for_capacity(
                        monitor, last_counter=last_counter
                    )
                    request = pending_requests.popleft()
                    tasks.append(asyncio.create_task(_process_payload(request)))
                    if len(tasks) >= runtime_controls.batch_size:
                        await asyncio.gather(*tasks)
                        tasks.clear()

                if producer_exhausted and not pending_requests:
                    break

            if tasks:
                await asyncio.gather(*tasks)

            finished_at = _now_utc()
            duration_ms = (perf_counter() - start_time) * 1000

            latency_percentiles = _calculate_percentiles(metrics_state["durations"])
            guardrail_actions = [
                GuardrailAction(type=key, count=value)
                for key, value in sorted(runtime_controls.guardrail_actions.items())
            ]

            summary = ImportSummary(
                metrics=JobMetrics(
                    total_requests=metrics_state["total_requests"],
                    success_count=metrics_state["success_count"],
                    failed_count=metrics_state["failed_count"],
                    error_count=metrics_state["error_count"],
                    latency_histogram=dict(metrics_state["latency_histogram"]),
                    peak_concurrency=metrics_state["peak_concurrency"],
                    retry_count=metrics_state["retry_count"],
                    permanent_failures=metrics_state["permanent_failures"],
                ),
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                total_processing_ms=float(sum(metrics_state["durations"])),
                latency_percentiles=latency_percentiles,
                cpu_samples=list(monitor.cpu_samples),
                memory_samples=list(monitor.memory_samples),
                guardrail_actions=guardrail_actions,
                peakCpu=monitor.peakCpu,
                peakMemoryMb=monitor.peakMemoryMb,
                throttleCount=monitor.throttleCount,
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
    guardrail_actions: dict[str, int] = field(default_factory=dict)

    async def wait_for_capacity(
        self,
        monitor: ResourceMonitor | None,
        *,
        last_counter: int | None = None,
    ) -> int | None:
        """Pause execution until resource utilisation is within guardrails."""

        if self.cpu_threshold is None and self.memory_threshold_mb is None:
            return last_counter
        if monitor is None:
            return last_counter

        counter = last_counter
        if counter is None:
            counter = await monitor.wait_for_sample(counter)

        while True:
            throttle, reasons = monitor.check_thresholds(
                cpu_threshold=self.cpu_threshold,
                memory_threshold_mb=self.memory_threshold_mb,
            )
            if not throttle:
                try:
                    counter = await asyncio.wait_for(
                        monitor.wait_for_sample(counter), timeout=0
                    )
                except asyncio.TimeoutError:
                    pass
                return counter

            monitor.record_throttle(reasons)
            self.guardrail_actions["throttle"] = self.guardrail_actions.get("throttle", 0) + 1
            for reason in reasons:
                self.guardrail_actions[reason] = self.guardrail_actions.get(reason, 0) + 1

            await asyncio.sleep(self.pause_seconds)
            counter = await monitor.wait_for_sample(counter)


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


__all__ = [
    "GuardrailAction",
    "GuardrailOverloadError",
    "ImportProgress",
    "ImportJobRunner",
    "ImportRuntimeControls",
    "ImportSummary",
    "JobMetrics",
    "configure_import_runtime",
]
