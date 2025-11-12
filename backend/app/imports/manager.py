"""Background import manager coordinating pipeline execution for CSV payloads."""

from __future__ import annotations

import asyncio
import csv
import io
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, MutableMapping, Sequence

from ..config import Settings
from ..pipeline.pipeline import HolidaySearchPipeline, PipelineRunResult


@dataclass(frozen=True, slots=True)
class ImportSummary:
    """Immutable aggregate emitted once a job has finished processing."""

    job_id: str
    status: str
    submitted_at: datetime
    completed_at: datetime
    total_rows: int
    processed_rows: int
    success_count: int
    mismatch_count: int
    error_count: int
    timings: dict[str, float]
    usage_footprint: dict[str, float]
    message: str | None = None


@dataclass(slots=True)
class ImportStatusSnapshot:
    """Lightweight, mutable view of an in-flight job."""

    job_id: str
    status: str
    submitted_at: datetime
    total_rows: int
    processed_rows: int = 0
    success_count: int = 0
    mismatch_count: int = 0
    error_count: int = 0
    completed_at: datetime | None = None
    message: str | None = None
    timings: dict[str, float] = field(default_factory=dict)
    usage_footprint: dict[str, float] = field(default_factory=dict)

    def copy(self) -> "ImportStatusSnapshot":
        """Create a shallow copy suitable for response serialization."""

        return ImportStatusSnapshot(
            job_id=self.job_id,
            status=self.status,
            submitted_at=self.submitted_at,
            total_rows=self.total_rows,
            processed_rows=self.processed_rows,
            success_count=self.success_count,
            mismatch_count=self.mismatch_count,
            error_count=self.error_count,
            completed_at=self.completed_at,
            message=self.message,
            timings=dict(self.timings),
            usage_footprint=dict(self.usage_footprint),
        )

    def finalise(self) -> ImportSummary:
        """Convert the mutable snapshot into an immutable summary."""

        if self.completed_at is None:
            raise RuntimeError("Cannot finalise an import job that has not completed")

        return ImportSummary(
            job_id=self.job_id,
            status=self.status,
            submitted_at=self.submitted_at,
            completed_at=self.completed_at,
            total_rows=self.total_rows,
            processed_rows=self.processed_rows,
            success_count=self.success_count,
            mismatch_count=self.mismatch_count,
            error_count=self.error_count,
            timings=dict(self.timings),
            usage_footprint=dict(self.usage_footprint),
            message=self.message,
        )


class ImportManager:
    """Coordinate CSV imports with bounded concurrency and rolling summaries."""

    def __init__(
        self,
        *,
        pipeline: HolidaySearchPipeline,
        settings: Settings,
        max_concurrency: int | None = None,
        summary_ttl_seconds: float = 3600.0,
    ) -> None:
        self._pipeline = pipeline
        self._settings = settings
        self._max_concurrency = max(
            1, int(max_concurrency or settings.import_max_concurrency)
        )
        self._queue_limit = settings.import_queue_limit
        self._batch_size = settings.import_batch_size
        self._max_pending_jobs = settings.import_max_pending_jobs
        self._summary_ttl = max(summary_ttl_seconds, 60.0)
        self._executor = ThreadPoolExecutor(max_workers=self._max_concurrency)
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._lock = asyncio.Lock()
        self._jobs: dict[str, ImportStatusSnapshot] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._summaries: dict[str, tuple[ImportSummary, float]] = {}

    @property
    def max_concurrency(self) -> int:
        """Return the configured concurrency cap."""

        return self._max_concurrency

    async def submit_csv(self, payload: bytes | str, *, filename: str | None = None) -> str:
        """Parse an uploaded CSV payload and enqueue a new import job."""

        del filename  # currently unused but reserved for future diagnostics
        if isinstance(payload, bytes):
            text = payload.decode("utf-8-sig")
        else:
            text = payload

        buffer = io.StringIO(text)
        reader = csv.DictReader(buffer)
        rows = [dict(row) for row in reader]
        if not rows:
            raise ValueError("CSV payload must contain at least one data row")

        return await self.submit_rows(rows)

    async def submit_rows(self, rows: Iterable[Mapping[str, object]]) -> str:
        """Accept already-parsed rows and start a background job."""

        materialised = [dict(row) for row in rows]
        if not materialised:
            raise ValueError("Import request must include at least one row")
        if len(materialised) > self._batch_size:
            raise ValueError(
                f"Import request exceeds maximum batch size of {self._batch_size} rows"
            )

        job_id = self._generate_job_id()
        snapshot = ImportStatusSnapshot(
            job_id=job_id,
            status="pending",
            submitted_at=datetime.now(timezone.utc),
            total_rows=len(materialised),
        )

        await self._register_job(job_id, snapshot)
        task = asyncio.create_task(self._run_job(job_id, snapshot, materialised))
        async with self._lock:
            self._tasks[job_id] = task
        return job_id

    async def get_status(self, job_id: str) -> ImportStatusSnapshot:
        """Return a snapshot describing the current state of a job."""

        await self._evict_expired()
        async with self._lock:
            snapshot = self._jobs.get(job_id)
            if snapshot is not None:
                return snapshot.copy()
            summary = self._summaries.get(job_id)
        if summary is not None:
            return ImportStatusSnapshot(
                job_id=summary[0].job_id,
                status=summary[0].status,
                submitted_at=summary[0].submitted_at,
                total_rows=summary[0].total_rows,
                processed_rows=summary[0].processed_rows,
                success_count=summary[0].success_count,
                mismatch_count=summary[0].mismatch_count,
                error_count=summary[0].error_count,
                completed_at=summary[0].completed_at,
                message=summary[0].message,
                timings=dict(summary[0].timings),
                usage_footprint=dict(summary[0].usage_footprint),
            )
        raise LookupError(f"Import job '{job_id}' not found")

    async def get_summary(self, job_id: str) -> ImportSummary | None:
        """Return the immutable summary for a completed job when available."""

        await self._evict_expired()
        async with self._lock:
            payload = self._summaries.get(job_id)
        if payload is None:
            return None
        return payload[0]

    async def _register_job(self, job_id: str, snapshot: ImportStatusSnapshot) -> None:
        async with self._lock:
            active_jobs = len(self._jobs)
            if active_jobs >= self._queue_limit:
                raise RuntimeError(
                    "Import queue is full; please wait for existing jobs to finish"
                )
            if self._max_pending_jobs is not None:
                pending_jobs = sum(1 for job in self._jobs.values() if job.status == "pending")
                if pending_jobs >= self._max_pending_jobs:
                    raise RuntimeError(
                        "Too many import jobs are pending; please retry once some have started"
                    )
            self._jobs[job_id] = snapshot
        await self._evict_expired()

    async def _run_job(
        self,
        job_id: str,
        snapshot: ImportStatusSnapshot,
        rows: Sequence[MutableMapping[str, object]],
    ) -> None:
        snapshot.status = "running"
        try:
            for row in rows:
                await self._process_row(snapshot, row)
        except Exception as exc:  # pragma: no cover - defensive guard
            snapshot.status = "failed"
            snapshot.message = str(exc)
        else:
            snapshot.status = "completed"
        finally:
            snapshot.completed_at = datetime.now(timezone.utc)
            summary = snapshot.finalise()
            async with self._lock:
                self._jobs.pop(job_id, None)
                self._tasks.pop(job_id, None)
                self._summaries[job_id] = (summary, time.monotonic() + self._summary_ttl)

    async def _process_row(
        self,
        snapshot: ImportStatusSnapshot,
        row: MutableMapping[str, object],
    ) -> None:
        utterance, method = self._extract_utterance(row)
        snapshot.processed_rows += 1

        if not utterance:
            snapshot.error_count += 1
            snapshot.message = "Encountered row with empty utterance"
            snapshot.usage_footprint["rowsProcessed"] = float(snapshot.processed_rows)
            return

        loop = asyncio.get_running_loop()
        try:
            async with self._semaphore:
                result = await loop.run_in_executor(
                    self._executor,
                    self._pipeline.run,
                    utterance,
                    method,
                )
        except Exception as exc:  # pragma: no cover - pipeline failure path
            snapshot.error_count += 1
            snapshot.message = str(exc)
            snapshot.usage_footprint["rowsProcessed"] = float(snapshot.processed_rows)
            return

        self._aggregate_result(snapshot, result)
        snapshot.usage_footprint["rowsProcessed"] = float(snapshot.processed_rows)

    def _aggregate_result(
        self,
        snapshot: ImportStatusSnapshot,
        result: PipelineRunResult,
    ) -> None:
        status = (result.status or "").lower()
        if status == "success":
            snapshot.success_count += 1
        elif status == "failed":
            snapshot.mismatch_count += 1
        else:
            snapshot.error_count += 1

        for key, value in result.timings.items():
            if isinstance(value, (int, float)):
                snapshot.timings[key] = snapshot.timings.get(key, 0.0) + float(value)

        usage = defaultdict(float, snapshot.usage_footprint)
        metadata = result.metadata or {}
        llm_metadata = metadata.get("llm") if isinstance(metadata, Mapping) else None
        if isinstance(llm_metadata, Mapping):
            usage["llmCalls"] += 1.0
            token_usage = llm_metadata.get("tokenUsage") or llm_metadata.get("usage")
            if isinstance(token_usage, Mapping):
                for key, value in token_usage.items():
                    if isinstance(value, (int, float)):
                        usage_key = f"tokens_{key}"
                        usage[usage_key] += float(value)

        snapshot.usage_footprint = dict(usage)

    async def _evict_expired(self) -> None:
        now = time.monotonic()
        async with self._lock:
            expired = [key for key, (_, expiry) in self._summaries.items() if expiry <= now]
            for key in expired:
                self._summaries.pop(key, None)

    def _extract_utterance(self, row: Mapping[str, object]) -> tuple[str, str | None]:
        text_value: str = ""
        for key in ("text", "utterance", "input", "transcript"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                text_value = value.strip()
                break

        method_value: str | None = None
        for key in ("method", "method_id", "methodId"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                method_value = value.strip()
                break

        return text_value, method_value

    def _generate_job_id(self) -> str:
        return f"imp-{int(time.time() * 1000)}-{id(self):x}-{len(self._jobs) + len(self._summaries)}"


__all__ = [
    "ImportManager",
    "ImportStatusSnapshot",
    "ImportSummary",
]

