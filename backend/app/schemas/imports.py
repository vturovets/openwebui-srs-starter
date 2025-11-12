"""Serialisable schemas for import job summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..services import ImportSummary as ServiceImportSummary


class ImportCounts(BaseModel):
    """Aggregate outcome counts captured for an import job."""

    requests: int = Field(..., description="Total number of requests scheduled for the job.")
    succeeded: int = Field(..., description="Number of requests that completed successfully.")
    failed: int = Field(..., description="Number of requests that completed with validation failures.")
    errored: int = Field(..., description="Number of requests that raised unexpected errors.")

    model_config = ConfigDict(populate_by_name=True)


class ImportDurations(BaseModel):
    """Duration totals associated with an import job."""

    job_ms: float = Field(..., alias="jobMs", description="Wall-clock duration for the import job (ms).")
    processing_ms: float = Field(
        ..., alias="processingMs", description="Sum of request processing times observed (ms)."
    )

    model_config = ConfigDict(populate_by_name=True)


class ImportLatency(BaseModel):
    """Latency percentile statistics derived from processed requests."""

    p50_ms: float | None = Field(default=None, alias="p50Ms", description="Median request latency (ms).")
    p95_ms: float | None = Field(
        default=None, alias="p95Ms", description="95th percentile request latency (ms)."
    )

    model_config = ConfigDict(populate_by_name=True)


class ImportResources(BaseModel):
    """Resource utilisation snapshot collected while the import job ran."""

    peak_cpu: float | None = Field(default=None, alias="peakCpu", description="Peak CPU usage (percent).")
    peak_memory_mb: float | None = Field(
        default=None, alias="peakMemoryMb", description="Peak memory consumption (MB)."
    )
    throttle_count: int = Field(
        default=0, alias="throttleCount", description="Number of throttling events observed."
    )

    model_config = ConfigDict(populate_by_name=True)


class ImportSummary(BaseModel):
    """Top-level summary returned to clients after an import completes."""

    status: Literal["success", "partial", "error"] = Field(
        ..., description="Overall status derived from import outcome counts."
    )
    mode: str | None = Field(
        default=None, description="Interaction mode associated with the import batch, when known."
    )
    counts: ImportCounts = Field(..., description="Aggregated request outcome counts.")
    durations: ImportDurations = Field(..., description="Wall-clock and processing time totals (ms).")
    latency: ImportLatency = Field(..., description="Key latency percentile measurements (ms).")
    started_at: datetime = Field(..., alias="startedAt", description="Timestamp when the job started.")
    finished_at: datetime = Field(..., alias="finishedAt", description="Timestamp when the job finished.")
    resources: ImportResources = Field(
        ..., description="Resource usage metrics captured during job execution."
    )
    guardrail_breaches: dict[str, int] = Field(
        default_factory=dict,
        alias="guardrailBreaches",
        description="Counts of guardrail actions triggered while scheduling work.",
    )

    model_config = ConfigDict(populate_by_name=True)


def build_import_summary(summary: ServiceImportSummary, *, mode: str | None) -> ImportSummary:
    """Transform a service-layer summary into the public API representation."""

    counts = ImportCounts(
        requests=summary.metrics.total_requests,
        succeeded=summary.metrics.success_count,
        failed=summary.metrics.failed_count,
        errored=summary.metrics.error_count,
    )
    durations = ImportDurations(jobMs=summary.duration_ms, processingMs=summary.total_processing_ms)
    percentiles = summary.latency_percentiles
    latency = ImportLatency(
        p50Ms=percentiles.get("p50"),
        p95Ms=percentiles.get("p95"),
    )
    resources = ImportResources(
        peakCpu=summary.peakCpu,
        peakMemoryMb=summary.peakMemoryMb,
        throttleCount=summary.throttleCount,
    )
    guardrail_breaches = {action.type: action.count for action in summary.guardrail_actions}

    status = "success"
    if counts.errored:
        status = "error"
    elif counts.failed:
        status = "partial"

    return ImportSummary(
        status=status,
        mode=mode,
        counts=counts,
        durations=durations,
        latency=latency,
        startedAt=summary.started_at,
        finishedAt=summary.finished_at,
        resources=resources,
        guardrailBreaches=guardrail_breaches,
    )


__all__ = [
    "ImportCounts",
    "ImportDurations",
    "ImportLatency",
    "ImportResources",
    "ImportSummary",
    "build_import_summary",
]
