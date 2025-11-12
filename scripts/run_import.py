#!/usr/bin/env python3
"""Utility script to execute bulk imports and display the aggregate summary."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
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
from backend.app.services import ImportJobRunner


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
    summary = await runner.run_import(requests)
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
