"""Tests covering the import job runner orchestration."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Iterable

from backend.app.api.routes import ParseRequest
from backend.app.config import Settings
from backend.app.services.import_runner import (
    DEFAULT_LATENCY_BUCKETS,
    ImportJobRunner,
    ImportSummary,
)


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

    assert pipeline.calls == total
    assert summary.metrics.total_requests == total
    assert summary.metrics.success_count == successes
    assert summary.metrics.failed_count == failures
    assert summary.metrics.error_count == errors

    histogram = summary.metrics.latency_histogram
    expected = {
        _bucket_label(lower, upper): 0 for lower, upper in DEFAULT_LATENCY_BUCKETS
    }
    expected[_bucket_label(0.0, 100.0)] = successes
    expected[_bucket_label(100.0, 250.0)] = failures
    expected[_bucket_label(1000.0, 2000.0)] = errors

    for label, count in expected.items():
        assert histogram[label] == count


def _bucket_label(lower: float, upper: float | None) -> str:
    lower_display = int(lower)
    if upper is None:
        return f"{lower_display}ms+"
    upper_display = int(upper) - 1
    return f"{lower_display}-{upper_display}ms"

