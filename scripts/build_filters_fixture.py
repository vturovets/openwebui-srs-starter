"""Convert documentation filters/options CSV into runtime fixture format.

This utility ingests the canonical list of filters and options from
``docs/filters_options.csv`` (or another source) and rewrites it using the
schema expected by the backend catalogue loader. It normalizes identifiers,
optionally slugifying them, and keeps any provided synonyms column intact.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

DEFAULT_INPUT = Path("docs/filters_options.csv")
DEFAULT_OUTPUT = Path("fixtures/filters_options.csv")
ID_STRATEGIES = ("slug", "source")

RE_SLUG = re.compile(r"[^a-z0-9]+")


class ConversionError(Exception):
    """Raised when the input CSV cannot be converted safely."""


class IdGenerator:
    """Generate consistent, collision-safe identifiers."""

    def __init__(self, strategy: str) -> None:
        if strategy not in ID_STRATEGIES:
            raise ValueError(f"Unknown id strategy '{strategy}' (expected one of {ID_STRATEGIES})")
        self.strategy = strategy
        self._filter_slug_for_name: dict[str, str] = {}
        self._filter_name_for_slug: dict[str, str] = {}
        self._option_slugs_for_filter: dict[str, dict[str, str]] = defaultdict(dict)
        self._option_names_for_slug: dict[str, dict[str, str]] = defaultdict(dict)

    def filter_id(self, filter_name: str, source_id: str) -> str:
        if self.strategy == "source":
            return source_id.strip()

        slug = slugify(filter_name)
        if slug in self._filter_name_for_slug and self._filter_name_for_slug[slug] != filter_name:
            raise ConversionError(
                f"Filter name collision detected: '{filter_name}' conflicts with '{self._filter_name_for_slug[slug]}'"
            )
        self._filter_slug_for_name.setdefault(filter_name, slug)
        self._filter_name_for_slug.setdefault(slug, filter_name)
        return slug

    def option_id(self, filter_id: str, option_name: str, source_id: str) -> str:
        if self.strategy == "source":
            return source_id.strip()

        slug = slugify(option_name)
        assigned_names = self._option_names_for_slug[filter_id]
        if slug in assigned_names and assigned_names[slug] != option_name:
            # Disambiguate while keeping both options
            suffix = 2
            candidate = f"{slug}_{suffix}"
            while candidate in assigned_names and assigned_names[candidate] != option_name:
                suffix += 1
                candidate = f"{slug}_{suffix}"
            slug = candidate
        self._option_slugs_for_filter[filter_id].setdefault(option_name, slug)
        assigned_names.setdefault(slug, option_name)
        return slug


def slugify(value: str) -> str:
    normalized = RE_SLUG.sub("_", value.lower()).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized:
        raise ConversionError(f"Unable to generate identifier from empty value '{value}'")
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert docs filters/options CSV into fixture format")
    parser.add_argument("--input", default=DEFAULT_INPUT, type=Path, help="Source CSV path (defaults to docs/filters_options.csv)")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        type=Path,
        help="Destination CSV path (defaults to fixtures/filters_options.csv)",
    )
    parser.add_argument(
        "--id-strategy",
        choices=ID_STRATEGIES,
        default="slug",
        help="Whether to reuse provided IDs (source) or slugify names (slug)",
    )
    return parser.parse_args()


def load_rows(input_path: Path) -> Iterable[dict[str, str]]:
    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"filterId", "filterName", "optionId", "optionName"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                missing = required.difference(set(reader.fieldnames or ()))
                raise ConversionError(
                    f"Input CSV is missing required columns: {', '.join(sorted(missing))}"
                )
            for row in reader:
                yield row
    except OSError as exc:
        raise ConversionError(f"Unable to read input CSV '{input_path}': {exc}") from exc
    except csv.Error as exc:  # pragma: no cover - csv parsing errors
        raise ConversionError(f"Invalid CSV structure: {exc}") from exc


def convert_rows(rows: Iterable[dict[str, str]], strategy: str) -> list[dict[str, str]]:
    generator = IdGenerator(strategy)
    converted: list[dict[str, str]] = []

    for row in rows:
        filter_name = (row.get("filterName") or "").strip()
        option_name = (row.get("optionName") or "").strip()
        source_filter_id = (row.get("filterId") or "").strip()
        source_option_id = (row.get("optionId") or "").strip()
        synonyms = (row.get("synonyms") or "").strip()

        if not filter_name or not option_name:
            raise ConversionError("Filter and option names must be provided for every row")
        if not source_filter_id or not source_option_id:
            raise ConversionError("Input IDs must be provided for every row")

        filter_id = generator.filter_id(filter_name, source_filter_id)
        option_id = generator.option_id(filter_id, option_name, source_option_id)

        converted.append(
            {
                "filterId": filter_id,
                "filterLabel": filter_name,
                "optionId": option_id,
                "optionLabel": option_name,
                "synonyms": synonyms,
            }
        )

    return converted


def write_rows(output_path: Path, rows: Iterable[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["filterId", "filterLabel", "optionId", "optionLabel", "synonyms"]
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    rows = list(load_rows(args.input))
    converted = convert_rows(rows, strategy=args.id_strategy)
    write_rows(args.output, converted)
    print(
        f"[build_filters_fixture] Wrote {len(converted)} rows to {args.output} using '{args.id_strategy}' identifiers"
    )


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
