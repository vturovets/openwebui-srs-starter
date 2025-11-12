#!/usr/bin/env python3
"""Utility script to execute bulk imports and display the aggregate summary."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.api.routes import ParseRequest
from backend.app.config import Settings
from backend.app.logging import ImportSummaryLogger, IMPORT_SUMMARY_LOG_FIELDS
from backend.app.pipeline.pipeline import HolidaySearchPipeline
from backend.app.schemas import build_import_summary
from backend.app.services import ImportJobRunner, ImportProgress


@dataclass(slots=True)
class _ProgressPrinter:
    """Render a textual progress indicator for import execution."""

    total: int
    width: int = 30
    _last_line_length: int = 0

    def update(self, progress: ImportProgress) -> None:
        processed = progress.processed
        success = progress.status_counts.get("success", 0)
        failed = progress.status_counts.get("failed", 0)
        error = progress.status_counts.get("error", 0)

        ratio = processed / self.total if self.total else 0.0
        filled = int(self.width * ratio)
        bar = "#" * filled + "-" * (self.width - filled)
        percent = ratio * 100 if self.total else 0.0
        line = (
            f"[{bar}] {processed}/{self.total} ({percent:5.1f}%) "
            f"success={success} failed={failed} error={error}"
        )

        padding = max(0, self._last_line_length - len(line))
        sys.stderr.write("\r" + line + (" " * padding))
        sys.stderr.flush()
        self._last_line_length = len(line)

    def finish(self) -> None:
        if self._last_line_length:
            sys.stderr.write("\n")
            sys.stderr.flush()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "batch",
        type=Path,
        help="Path to a JSON file containing an array of import requests.",
    )
    parser.add_argument(
        "--mode",
        help="Default interaction mode applied to requests when not specified individually.",
    )
    parser.add_argument(
        "--method",
        help="Default pipeline method identifier applied when entries omit one.",
    )
    return parser.parse_args(argv)


def _normalise_entry(
    entry: object,
    *,
    default_mode: str | None,
    default_method: str | None,
) -> ParseRequest:
    if isinstance(entry, str):
        text = entry.strip()
        if not text:
            raise ValueError("Batch entries provided as strings must be non-empty")
        return ParseRequest(text=text, mode=default_mode, method=default_method)

    if isinstance(entry, Mapping):
        text = str(entry.get("text", "")).strip()
        if not text:
            raise ValueError("Batch entries must include a 'text' field")
        mode = entry.get("mode") or default_mode
        method = entry.get("method") or default_method
        return ParseRequest(text=text, mode=mode, method=method)

    raise ValueError("Batch entries must be strings or objects with a 'text' property")


def _load_requests(
    batch_path: Path,
    *,
    default_mode: str | None,
    default_method: str | None,
) -> list[ParseRequest]:
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Batch file must contain a JSON array of requests")

    requests: list[ParseRequest] = []
    for index, entry in enumerate(payload):
        try:
            requests.append(
                _normalise_entry(
                    entry,
                    default_mode=default_mode,
                    default_method=default_method,
                )
            )
        except ValueError as exc:  # pragma: no cover - defensive validation guard
            raise ValueError(f"Invalid batch entry at index {index}: {exc}") from exc

    if not requests:
        raise ValueError("Batch file must contain at least one request")

    return requests


def _derive_batch_mode(requests: Sequence[ParseRequest], default_mode: str | None) -> str | None:
    if default_mode:
        return default_mode
    modes = {request.mode for request in requests if request.mode}
    if len(modes) == 1:
        return modes.pop()
    return None


async def _execute_import(
    requests: Sequence[ParseRequest],
    *,
    settings: Settings,
) -> object:
    pipeline = HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)
    runner = ImportJobRunner(pipeline=pipeline, settings=settings, logger=None)
    progress_printer: _ProgressPrinter | None = None
    if sys.stderr.isatty():
        progress_printer = _ProgressPrinter(total=len(requests))

    async def _on_progress(progress: ImportProgress) -> None:
        if progress_printer is not None:
            progress_printer.update(progress)

    try:
        summary = await runner.run_import(
            requests,
            progress_callback=_on_progress if progress_printer is not None else None,
            total=len(requests),
        )
    finally:
        if progress_printer is not None:
            progress_printer.finish()
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        requests = _load_requests(
            args.batch,
            default_mode=args.mode,
            default_method=args.method,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    settings = Settings()
    settings.ensure_directories()

    summary = asyncio.run(_execute_import(requests, settings=settings))

    batch_mode = _derive_batch_mode(requests, args.mode)
    summary_model = build_import_summary(summary, mode=batch_mode)

    if settings.import_summary_path is not None:
        summary_logger = ImportSummaryLogger(
            path=settings.import_summary_path,
            fieldnames=IMPORT_SUMMARY_LOG_FIELDS,
            delimiter=settings.import_summary_delimiter,
        )
        summary_logger.log(summary_model)

    print(json.dumps(summary_model.model_dump(mode="json", by_alias=True), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
