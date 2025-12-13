from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

from dotenv import find_dotenv, load_dotenv

from .io import (
    InputRow,
    InputValidationError,
    build_processed_index,
    chunk_rows,
    compute_file_hash,
    load_existing_output,
    read_input_rows,
    write_metadata,
    write_output,
)
from .openai_client import ResponsesAPI
from .prompt import PROMPT_VERSION, load_prompt_text
from .validate import ResponseValidationError, enforce_schema, sanitize_synonyms

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


DEFAULT_BATCH_SIZE = 150
DEFAULT_MODEL = "gpt-5.2"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_RATE_LIMIT_SLEEP = 2.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_TIMEOUT = 120
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class DryRunComplete(Exception):
    pass


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synonyms lexicon via OpenAI Responses API"
    )
    parser.add_argument("--input", required=True, help="Path to input CSV")
    parser.add_argument("--output", required=True, help="Path to output JSON file")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-synonyms", type=int, default=10)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--raw-dir", type=str)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rate-limit-sleep", type=float, default=DEFAULT_RATE_LIMIT_SLEEP)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    return parser.parse_args(argv)


def _store_raw(
    raw_dir: Path, batch_number: int, response: List[Dict[str, object]], request: Dict[str, object]
) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"batch_{batch_number}.json"
    with raw_path.open("w", encoding="utf-8") as handle:
        json.dump({"response": response, "request": request}, handle, ensure_ascii=False, indent=2)


def _apply_sanitization(
    batch_rows: List[InputRow],
    raw_results: List[Dict[str, object]],
    max_synonyms: int,
) -> List[Dict[str, object]]:
    sanitized: List[Dict[str, object]] = []
    for source, result in zip(batch_rows, raw_results):
        synonyms = result.get("synonyms", []) if isinstance(result, dict) else []
        cleaned_synonyms, removals = sanitize_synonyms(source.filterId, synonyms, max_synonyms)
        notes_parts = []
        removed_total = sum(removals.values())
        if removed_total:
            parts = [f"{key}={value}" for key, value in removals.items() if value]
            notes_parts.append(f"removed={removed_total} ({', '.join(parts)})")
        if "notes" in result and result["notes"]:
            notes_parts.append(str(result["notes"]))
        entry = {
            "ID": source.ID,
            "filterId": source.filterId,
            "filterName": source.filterName,
            "optionId": source.optionId,
            "optionName": source.optionName,
            "synonyms": cleaned_synonyms,
        }
        if notes_parts:
            entry["notes"] = "; ".join(notes_parts)
        sanitized.append(entry)
    return sanitized


def _ensure_max_synonyms(max_synonyms: int) -> None:
    if not 1 <= max_synonyms <= 10:
        raise ValueError("--max-synonyms must be between 1 and 10")


def load_environment(dotenv_path: Path | None = DEFAULT_ENV_PATH) -> None:
    """Load environment variables from a local .env file if present."""

    resolved_path = dotenv_path if dotenv_path and dotenv_path.exists() else None
    if not resolved_path:
        found = find_dotenv(usecwd=True)
        resolved_path = Path(found) if found else None

    if resolved_path:
        load_dotenv(resolved_path, override=False)


def process_batches(
    batches: Iterable[List[InputRow]],
    client: ResponsesAPI,
    instructions: str,
    max_synonyms: int,
    raw_dir: Path | None,
    resume_offset: int = 0,
) -> List[Dict[str, object]]:
    all_results: List[Dict[str, object]] = []
    for batch_number, batch_rows in enumerate(batches, start=resume_offset + 1):
        logger.info("Processing batch %s with %s rows", batch_number, len(batch_rows))
        raw_results = client.generate(
            instructions, [row.to_payload() for row in batch_rows], max_synonyms
        )
        enforce_schema(raw_results)
        sanitized = _apply_sanitization(batch_rows, raw_results, max_synonyms)
        all_results.extend(sanitized)
        if raw_dir:
            request_metadata = {
                "batch_number": batch_number,
                "model": client.model,
                "temperature": client.temperature,
                "max_synonyms": max_synonyms,
                "row_count": len(batch_rows),
            }
            _store_raw(raw_dir, batch_number, raw_results, request_metadata)
    return all_results


def build_metadata(
    input_path: Path,
    model: str,
    temperature: float,
    max_synonyms: int,
    prompt_version: str,
    total_rows: int,
    processed_rows: int,
) -> Dict[str, object]:
    return {
        "input_path": str(input_path),
        "input_sha256": compute_file_hash(input_path),
        "model": model,
        "temperature": temperature,
        "max_synonyms": max_synonyms,
        "prompt_version": prompt_version,
        "total_rows": total_rows,
        "processed_rows": processed_rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def run(args: argparse.Namespace) -> None:
    load_environment()
    _ensure_max_synonyms(args.max_synonyms)
    input_path = Path(args.input)
    output_path = Path(args.output)
    raw_dir = Path(args.raw_dir) if args.raw_dir else None

    try:
        rows = read_input_rows(input_path)
    except (InputValidationError, FileNotFoundError) as exc:
        logger.error("Input validation failed: %s", exc)
        raise SystemExit(1)

    existing: List[Dict[str, object]] = []
    processed_index: Dict[tuple, Dict[str, object]] = {}
    if args.resume and output_path.exists():
        existing = load_existing_output(output_path)
        processed_index = build_processed_index(existing)
        logger.info("Resuming run: %s existing rows detected", len(processed_index))

    pending_rows = [row for row in rows if (row.filterId, row.optionId) not in processed_index]
    if args.dry_run:
        logger.info(
            "Dry run complete: total rows=%s, pending=%s, batch_size=%s",
            len(rows),
            len(pending_rows),
            args.batch_size,
        )
        raise DryRunComplete()

    instructions = load_prompt_text()
    client = ResponsesAPI(
        model=args.model,
        temperature=args.temperature,
        timeout=args.timeout,
        max_retries=args.max_retries,
        rate_limit_sleep=args.rate_limit_sleep,
    )

    batches = chunk_rows(pending_rows, args.batch_size)
    try:
        new_results = process_batches(
            batches=batches,
            client=client,
            instructions=instructions,
            max_synonyms=args.max_synonyms,
            raw_dir=raw_dir,
            resume_offset=len(processed_index) // max(args.batch_size, 1),
        )
    except ResponseValidationError as exc:
        logger.error("Response validation failed: %s", exc)
        raise SystemExit(1)

    merged = existing + new_results

    # Reorder to match input order, preserving existing results where applicable.
    result_index = {
        (
            entry["filterId"],
            entry["optionId"],
        ): entry
        for entry in merged
    }
    ordered_output = [
        result_index[(row.filterId, row.optionId)]
        for row in rows
        if (row.filterId, row.optionId) in result_index
    ]

    write_output(output_path, ordered_output)
    metadata = build_metadata(
        input_path=input_path,
        model=args.model,
        temperature=args.temperature,
        max_synonyms=args.max_synonyms,
        prompt_version=PROMPT_VERSION,
        total_rows=len(rows),
        processed_rows=len(ordered_output),
    )
    write_metadata(output_path.with_suffix(output_path.suffix + ".metadata.json"), metadata)


def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        run(args)
    except DryRunComplete:
        pass
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(1)
