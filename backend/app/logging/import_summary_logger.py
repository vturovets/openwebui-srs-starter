"""CSV sink dedicated to aggregated import summaries."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from ..schemas import ImportSummary


def _utc_timestamp() -> str:
    """Return the current UTC timestamp with millisecond precision."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _format_float(value: float | None) -> str:
    """Render floating point values for CSV output, omitting NaNs."""

    if value is None:
        return ""
    if math.isnan(value):
        return ""
    return f"{value:.2f}"


IMPORT_SUMMARY_LOG_FIELDS: tuple[str, ...] = (
    "Timestamp (UTC)",
    "Mode",
    "Status",
    "Requests",
    "Succeeded",
    "Failed",
    "Errored",
    "Job Duration (ms)",
    "Processing Duration (ms)",
    "Latency p50 (ms)",
    "Latency p95 (ms)",
    "Peak CPU (%)",
    "Peak Memory (MB)",
    "Throttle Count",
    "Guardrail Breaches",
    "Started At",
    "Finished At",
)


@dataclass(slots=True)
class ImportSummaryLogger:
    """Append aggregated import summary rows to a CSV file."""

    path: Path
    fieldnames: Sequence[str] = IMPORT_SUMMARY_LOG_FIELDS
    delimiter: str = ","
    _fieldnames: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._fieldnames = tuple(self.fieldnames)
        if len(self.delimiter) != 1:
            raise ValueError("CSV delimiter must be a single character")

    def log(self, summary: ImportSummary) -> None:
        """Persist a single summary row for the provided import job."""

        row = self._prepare_row(summary)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.path.exists() or self.path.stat().st_size == 0

        with self.path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=self.delimiter)
            if write_header:
                writer.writerow(self._fieldnames)
            writer.writerow([row.get(name, "") for name in self._fieldnames])

    def _prepare_row(self, summary: ImportSummary) -> dict[str, str]:
        guardrail_payload = (
            json.dumps(summary.guardrail_breaches, ensure_ascii=False)
            if summary.guardrail_breaches
            else ""
        )

        return {
            "Timestamp (UTC)": _utc_timestamp(),
            "Mode": summary.mode or "",
            "Status": summary.status,
            "Requests": str(summary.counts.requests),
            "Succeeded": str(summary.counts.succeeded),
            "Failed": str(summary.counts.failed),
            "Errored": str(summary.counts.errored),
            "Job Duration (ms)": _format_float(summary.durations.job_ms),
            "Processing Duration (ms)": _format_float(summary.durations.processing_ms),
            "Latency p50 (ms)": _format_float(summary.latency.p50_ms),
            "Latency p95 (ms)": _format_float(summary.latency.p95_ms),
            "Peak CPU (%)": _format_float(summary.resources.peak_cpu),
            "Peak Memory (MB)": _format_float(summary.resources.peak_memory_mb),
            "Throttle Count": str(summary.resources.throttle_count),
            "Guardrail Breaches": guardrail_payload,
            "Started At": summary.started_at.isoformat(timespec="milliseconds"),
            "Finished At": summary.finished_at.isoformat(timespec="milliseconds"),
        }


__all__ = ["ImportSummaryLogger", "IMPORT_SUMMARY_LOG_FIELDS"]
