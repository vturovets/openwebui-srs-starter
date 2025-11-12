"""Tests covering the import job runner orchestration."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Iterable

import pytest

from backend.app.api.routes import ParseRequest
from backend.app.config import Settings
import backend.app.services.import_runner as import_runner
from backend.app.services.import_runner import (
    DEFAULT_LATENCY_BUCKETS,
    ImportJobRunner,
    ImportProgress,
    ImportSummary,
    configure_import_runtime,
)
from backend.app.telemetry import resource_monitor


class _DummyLogger:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def log(self, entry: dict[str, object]) -> None:
        self.entries.append(entry)


def _fake_result(status: str, total_ms: float, method: str | None) -> SimpleNamespace:
    error_detail = "boom" if status == "error" else None
    normalized = SimpleNamespace(to_payload=lambda: {"status": status}) if status != "error" else None
    metadata = {"timings": {"totalMs": total_ms}}
    detection = SimpleNamespace(language="en", confidence=0.9)
    return SimpleNamespace(
        status=status,
        metadata=metadata,
        normalized=normalized,
        validation={"status": status},
        method_used=method or "auto",
        method_requested=method,
        timings={"totalMs": total_ms},
        attempts=[],
        error=error_detail,
        extraction=None,
        detection=detection,
    )


class _RecordingPipeline:
    def __init__(self, statuses: Iterable[str], latency_ms: float) -> None:
        self.statuses = list(statuses)
        self.latency_ms = latency_ms
        self.calls: list[str] = []
        self._index = 0

    def run(self, text: str, *, method: str | None = None):
        status = self.statuses[self._index % len(self.statuses)]
        self._index += 1
        self.calls.append(text)
        return _fake_result(status, self.latency_ms, method)


class _ConcurrencyPipeline:
    def __init__(self, latency_ms: float, sleep_seconds: float) -> None:
        self.latency_ms = latency_ms
        self.sleep_seconds = sleep_seconds
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def run(self, text: str, *, method: str | None = None):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.sleep_seconds)
            return _fake_result("success", self.latency_ms, method)
        finally:
            with self._lock:
                self.active -= 1


def _make_requests(count: int) -> list[ParseRequest]:
    return [ParseRequest(text=f"request-{idx}") for idx in range(count)]


def _run(coro):
    return asyncio.run(coro)


def test_run_import_processes_all_payloads_and_invokes_callback():
    pipeline = _RecordingPipeline(statuses=["success", "failed", "success"], latency_ms=120.0)
    logger = _DummyLogger()
    runner = ImportJobRunner(
        pipeline=pipeline,
        settings=Settings(),
        logger=logger,
        concurrency_limit=4,
    )

    requests = _make_requests(9)
    captured_summary: ImportSummary | None = None

    async def _invoke() -> ImportSummary:
        nonlocal captured_summary

        async def _callback(summary: ImportSummary) -> None:
            nonlocal captured_summary
            captured_summary = summary

        return await runner.run_import(requests, summary_callback=_callback)

    summary = _run(_invoke())

    assert len(pipeline.calls) == len(requests)
    assert summary.metrics.total_requests == len(requests)
    assert summary.metrics.success_count == 6
    assert summary.metrics.failed_count == 3
    assert summary.metrics.error_count == 0
    assert captured_summary is summary
    assert len(logger.entries) == len(requests)
    assert "p95" in summary.latency_percentiles
    assert summary.total_processing_ms >= 0.0
    assert isinstance(summary.cpu_samples, list)
    assert isinstance(summary.memory_samples, list)
    assert isinstance(summary.guardrail_actions, list)
    assert summary.throttleCount >= 0
    assert summary.retryCount >= 0
    assert summary.permanentFailures >= 0
    if summary.peakCpu is not None:
        assert summary.peakCpu >= 0.0
    if summary.peakMemoryMb is not None:
        assert summary.peakMemoryMb >= 0.0


def test_run_import_emits_progress_updates():
    pipeline = _RecordingPipeline(statuses=["success"], latency_ms=75.0)
    runner = ImportJobRunner(
        pipeline=pipeline,
        settings=Settings(),
        logger=None,
        concurrency_limit=2,
    )

    requests = _make_requests(3)
    updates: list[ImportProgress] = []

    async def _invoke() -> ImportSummary:
        async def _progress(update: ImportProgress) -> None:
            updates.append(update)

        return await runner.run_import(
            requests,
            progress_callback=_progress,
            total=len(requests),
        )

    _run(_invoke())

    assert [update.processed for update in updates] == [1, 2, 3]
    assert all(update.total == len(requests) for update in updates)
    assert updates[-1].status_counts["success"] == len(requests)


def test_run_import_honours_concurrency_cap():
    pipeline = _ConcurrencyPipeline(latency_ms=200.0, sleep_seconds=0.01)
    runner = ImportJobRunner(
        pipeline=pipeline,
        settings=Settings(),
        logger=None,
        concurrency_limit=3,
    )

    requests = _make_requests(12)

    summary = _run(runner.run_import(requests))

    assert pipeline.peak <= 3
    assert summary.metrics.peak_concurrency <= 3
    assert summary.metrics.total_requests == len(requests)
    assert isinstance(summary.guardrail_actions, list)
    assert summary.total_processing_ms >= 0.0
    assert summary.retryCount >= 0
    assert summary.permanentFailures >= 0


def test_run_import_aggregates_large_batch_metrics():
    total = 1200
    successes = 1000
    failures = 100
    errors = total - successes - failures
    latencies = {
        "success": 50.0,
        "failed": 180.0,
        "error": 1400.0,
    }

    class _BulkPipeline:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, text: str, *, method: str | None = None):
            index = int(text.split("-")[-1])
            if index < successes:
                status = "success"
            elif index < successes + failures:
                status = "failed"
            else:
                status = "error"
            self.calls += 1
            return _fake_result(status, latencies[status], method)

    pipeline = _BulkPipeline()
    runner = ImportJobRunner(
        pipeline=pipeline,
        settings=Settings(),
        logger=None,
        concurrency_limit=8,
    )

    requests = _make_requests(total)
    summary = _run(runner.run_import(requests))

    assert pipeline.calls == total + summary.metrics.retry_count
    assert summary.metrics.retry_count == pipeline.calls - total
    assert summary.metrics.total_requests == total
    assert summary.metrics.success_count == successes
    assert summary.metrics.failed_count == failures
    assert summary.metrics.error_count == errors
    expected_processing = (
        successes * latencies["success"]
        + failures * latencies["failed"]
        + errors * latencies["error"]
    )
    assert summary.total_processing_ms == pytest.approx(expected_processing)

    histogram = summary.metrics.latency_histogram
    expected = {
        _bucket_label(lower, upper): 0 for lower, upper in DEFAULT_LATENCY_BUCKETS
    }
    expected[_bucket_label(0.0, 100.0)] = successes
    expected[_bucket_label(100.0, 250.0)] = failures
    expected[_bucket_label(1000.0, 2000.0)] = errors

    for label, count in expected.items():
        assert histogram[label] == count

    assert summary.latency_percentiles["p99"] >= max(latencies.values())


def test_run_import_retries_transient_errors():
    pipeline = _RecordingPipeline(statuses=["error", "success"], latency_ms=80.0)
    settings = Settings(import_retry_attempts=3, import_retry_backoff_seconds=0.0)
    runner = ImportJobRunner(
        pipeline=pipeline,
        settings=settings,
        logger=None,
        concurrency_limit=2,
    )

    summary = _run(runner.run_import(_make_requests(1)))

    assert len(pipeline.calls) == 2
    assert summary.metrics.success_count == 1
    assert summary.metrics.retry_count == 1
    assert summary.retryCount == 1
    assert summary.metrics.permanent_failures == 0
    assert summary.permanentFailures == 0


def test_run_import_marks_permanent_failures_after_max_attempts():
    pipeline = _RecordingPipeline(statuses=["error"], latency_ms=60.0)
    settings = Settings(import_retry_attempts=2, import_retry_backoff_seconds=0.0)
    runner = ImportJobRunner(
        pipeline=pipeline,
        settings=settings,
        logger=None,
        concurrency_limit=1,
    )

    summary = _run(runner.run_import(_make_requests(1)))

    assert len(pipeline.calls) == 2
    assert summary.metrics.error_count == 1
    assert summary.metrics.retry_count == 1
    assert summary.retryCount == 1
    assert summary.metrics.permanent_failures == 1
    assert summary.permanentFailures == 1


def test_configure_import_runtime_respects_limits():
    settings = Settings(
        import_worker_concurrency=4,
        import_max_concurrency=2,
        import_batch_size=5,
        import_cpu_threshold=85.0,
        import_memory_threshold_mb=3000,
        import_pause_seconds=0.2,
    )

    async def _invoke():
        return configure_import_runtime(settings, concurrency_override=10)

    runtime = _run(_invoke())

    assert runtime.semaphore._value == 2  # type: ignore[attr-defined]
    assert runtime.batch_size == 5
    assert runtime.cpu_threshold == 85.0
    assert runtime.memory_threshold_mb == 3000
    assert runtime.pause_seconds == 0.2


def test_runtime_controls_wait_for_capacity(monkeypatch):
    settings = Settings(
        import_cpu_threshold=10.0,
        import_memory_threshold_mb=1024,
        import_pause_seconds=0.01,
    )

    sleeps: list[float] = []
    original_sleep = import_runner.asyncio.sleep

    async def _fake_sleep(duration: float) -> None:
        sleeps.append(duration)
        await original_sleep(0)

    monkeypatch.setattr(import_runner.asyncio, "sleep", _fake_sleep)

    class _Sampler:
        def __init__(self) -> None:
            self._values = iter([(50.0, 0.0), (5.0, 0.0)])
            self._last = (5.0, 0.0)

        def __call__(self) -> tuple[float, float]:
            return next(self._values, self._last)

    async def _invoke() -> tuple[list[float], dict[str, int]]:
        runtime = configure_import_runtime(settings, concurrency_override=1)
        monitor = resource_monitor.ResourceMonitor(
            interval=0.001,
            cpu_threshold=runtime.cpu_threshold,
            memory_threshold_mb=runtime.memory_threshold_mb,
            sampler=_Sampler(),
        )
        async with monitor:
            await runtime.wait_for_capacity(monitor)
        return sleeps, runtime.guardrail_actions

    recorded_sleeps, guardrail_actions = _run(_invoke())

    assert recorded_sleeps
    assert recorded_sleeps[0] == settings.import_pause_seconds
    assert guardrail_actions["throttle"] >= 1
    assert guardrail_actions["cpu"] >= 1


def test_run_import_records_resource_peaks_and_throttling(monkeypatch):
    settings = Settings(
        import_cpu_threshold=60.0,
        import_memory_threshold_mb=50,
        import_pause_seconds=0.001,
    )

    samples = [
        (75.0, 40.0),
        (95.0, 80.0),
        (30.0, 20.0),
    ]

    class _Sampler:
        def __init__(self) -> None:
            self._values = iter(samples)
            self._last = samples[-1]

        def __call__(self) -> tuple[float, float]:
            value = next(self._values, self._last)
            return value

    monkeypatch.setattr(resource_monitor, "ProcessSampler", lambda: _Sampler())

    pipeline = _RecordingPipeline(statuses=["success"], latency_ms=50.0)
    runner = ImportJobRunner(
        pipeline=pipeline,
        settings=settings,
        logger=None,
        concurrency_limit=1,
    )

    summary = _run(runner.run_import(_make_requests(3)))

    assert summary.throttleCount >= 1
    assert summary.peakCpu is not None and summary.peakCpu >= 95.0
    assert summary.peakMemoryMb is not None and summary.peakMemoryMb >= 80.0


def _bucket_label(lower: float, upper: float | None) -> str:
    lower_display = int(lower)
    if upper is None:
        return f"{lower_display}ms+"
    upper_display = int(upper) - 1
    return f"{lower_display}-{upper_display}ms"

