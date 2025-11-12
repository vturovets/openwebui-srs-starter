import asyncio
import csv
import threading
import time
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routes import ImportStatusResponse
from backend.app.config import Settings
from backend.app.imports.manager import ImportManager, ImportStatusSnapshot
from backend.app.main import create_app
from backend.app.pipeline.pipeline import PipelineRunResult
from backend.app.dependencies import get_import_manager


class SummaryStubPipeline:
    """Pipeline stub that returns different statuses based on the utterance."""

    def run(self, utterance: str, method: str | None = None) -> PipelineRunResult:
        status = "success"
        timings: dict[str, float] = {"totalMs": 100.0, "languageMs": 25.0}
        metadata: dict[str, Any] = {"llm": {"tokenUsage": {"prompt": 10, "completion": 4}}}

        if "mismatch" in utterance:
            status = "failed"
            timings["totalMs"] = 120.0
        elif "error" in utterance:
            raise RuntimeError("pipeline failure")

        detection = SimpleNamespace(language="en", confidence=0.9)
        normalized = SimpleNamespace()

        return PipelineRunResult(
            status=status,
            method_requested=method or "rules-basic",
            method_used="rules-basic",
            detection=detection,
            extraction=None,
            normalized=normalized,
            validation={"status": "passed"},
            metadata=metadata,
            attempts=[],
            timings=timings,
            error=None,
        )


class ConcurrencyStubPipeline:
    """Pipeline stub that records the highest observed concurrency."""

    def __init__(self, delay: float = 0.02) -> None:
        self.delay = delay
        self.max_concurrency = 0
        self._current = 0
        self._lock = threading.Lock()

    def run(self, utterance: str, method: str | None = None) -> PipelineRunResult:
        with self._lock:
            self._current += 1
            self.max_concurrency = max(self.max_concurrency, self._current)
        try:
            time.sleep(self.delay)
        finally:
            with self._lock:
                self._current -= 1

        detection = SimpleNamespace(language="en", confidence=0.9)
        normalized = SimpleNamespace()
        return PipelineRunResult(
            status="success",
            method_requested="rules-basic",
            method_used="rules-basic",
            detection=detection,
            extraction=None,
            normalized=normalized,
            validation={"status": "passed"},
            metadata={},
            attempts=[],
            timings={"totalMs": self.delay * 1000},
            error=None,
        )


def test_import_manager_generates_summary() -> None:
    async def scenario() -> None:
        pipeline = SummaryStubPipeline()
        settings = Settings()
        manager = ImportManager(pipeline=pipeline, settings=settings, summary_ttl_seconds=300)

        rows = [
            {"text": "book trip"},
            {"text": "mismatch row"},
            {"text": "cause error"},
        ]

        job_id = await manager.submit_rows(rows)

        async def _wait_for_completion() -> ImportStatusSnapshot:
            while True:
                snapshot = await manager.get_status(job_id)
                if snapshot.status in {"completed", "failed"}:
                    return snapshot
                await asyncio.sleep(0.01)

        snapshot = await _wait_for_completion()
        summary = await manager.get_summary(job_id)

        assert snapshot.status == "completed"
        assert snapshot.total_rows == 3
        assert snapshot.success_count == 1
        assert snapshot.mismatch_count == 1
        assert snapshot.error_count == 1
        assert summary is not None
        assert summary.timings["totalMs"] == pytest.approx(220.0)
        assert summary.timings["languageMs"] == pytest.approx(50.0)
        assert summary.usage_footprint["llmCalls"] == pytest.approx(2.0)
        assert summary.usage_footprint["tokens_prompt"] == pytest.approx(20.0)
        assert summary.usage_footprint["rowsProcessed"] == pytest.approx(3.0)

    asyncio.run(scenario())


def test_import_manager_limits_concurrency() -> None:
    async def scenario() -> None:
        pipeline = ConcurrencyStubPipeline(delay=0.02)
        settings = Settings()
        manager = ImportManager(pipeline=pipeline, settings=settings, max_concurrency=2, summary_ttl_seconds=120)

        async def enqueue(index: int) -> str:
            return await manager.submit_rows([{ "text": f"row {index}" }])

        job_ids = await asyncio.gather(*(enqueue(idx) for idx in range(5)))

        async def wait_for(job_id: str) -> None:
            while True:
                snapshot = await manager.get_status(job_id)
                if snapshot.status in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.005)

        await asyncio.gather(*(wait_for(job_id) for job_id in job_ids))
        assert pipeline.max_concurrency <= manager.max_concurrency

    asyncio.run(scenario())


def test_import_endpoints_delegate_to_manager() -> None:
    app = create_app()

    class StubManager:
        def __init__(self) -> None:
            now = datetime.now(timezone.utc)
            self.payloads: list[bytes] = []
            self.snapshot = ImportStatusSnapshot(
                job_id="job-123",
                status="completed",
                submitted_at=now,
                total_rows=1,
                processed_rows=1,
                success_count=1,
                mismatch_count=0,
                error_count=0,
                completed_at=now,
                timings={"totalMs": 10.0},
                usage_footprint={"rowsProcessed": 1.0},
            )

        async def submit_csv(self, payload: bytes, *, filename: str | None = None) -> str:
            self.payloads.append(payload)
            return "job-123"

        async def get_status(self, job_id: str) -> ImportStatusSnapshot:
            if job_id != "job-123":
                raise LookupError("unknown job")
            return self.snapshot.copy()

    stub_manager = StubManager()
    app.dependency_overrides[get_import_manager] = lambda: stub_manager

    client = TestClient(app)

    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["text", "method"])
    writer.writerow(["hello world", "rules-basic"])
    response = client.post(
        "/v1/imports",
        files={"upload": ("import.csv", csv_buffer.getvalue(), "text/csv")},
    )

    assert response.status_code == 202
    assert response.json()["jobId"] == "job-123"
    assert stub_manager.payloads

    status_response = client.get("/v1/imports/job-123")
    assert status_response.status_code == 200
    payload = ImportStatusResponse.model_validate(status_response.json())
    assert payload.job_id == "job-123"

