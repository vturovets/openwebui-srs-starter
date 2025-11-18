"""Generate persisted popularity statistics from the demo dataset."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Callable, Iterable, Iterator, Mapping, MutableMapping

DEFAULT_TOP_N = 5
SCHEMA_VERSION = 1


@dataclass(slots=True)
class ParsedRow:
    """Typed representation of a CSV row."""

    duration: int | None
    rooms: int | None
    adults: int
    children: int
    infants: int
    start_date: str | None
    end_date: str | None
    departure_airport: str | None
    destinations: list[str]

    @property
    def party_tuple(self) -> tuple[int, int, int]:
        return (self.adults, self.children, self.infants)

    @property
    def interval(self) -> tuple[str, str] | None:
        if self.start_date and self.end_date:
            return (self.start_date, self.end_date)
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build popularity statistics JSON file")
    parser.add_argument("--csv", default="docs/demo_set_example.csv", help="Path to CSV input")
    parser.add_argument(
        "--output",
        default="fixtures/popularity_stats.json",
        help="Destination JSON file path",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Number of most common values to store per metric",
    )
    parser.add_argument(
        "--schema-version",
        type=int,
        default=SCHEMA_VERSION,
        help="Metadata schema version to emit",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON output with indentation",
    )
    return parser.parse_args()


def parse_int(value: str | None, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    value = value.strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def parse_optional_int(value: str | None) -> int | None:
    return parse_int(value, default=None)


def normalize_airport(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def normalize_destinations(value: str | None) -> list[str]:
    if value is None:
        return []
    parts = [segment.strip() for segment in value.replace("\n", " ").split(",")]
    return [part for part in parts if part]


def normalize_date(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.date().isoformat()
    print(f"[build_popularity_stats] Skipping unrecognized date value: {value}", file=sys.stderr)
    return None


def parse_row(row: Mapping[str, str]) -> ParsedRow:
    duration = parse_optional_int(row.get("duration"))
    rooms = parse_optional_int(row.get("rooms"))
    adults = parse_int(row.get("adults"), default=0) or 0
    children = parse_int(row.get("children"), default=0) or 0
    infants = parse_int(row.get("infants"), default=0) or 0
    start_date = normalize_date(row.get("startDepartureDate"))
    end_date = normalize_date(row.get("endDepartureDate"))
    departure_airport = normalize_airport(row.get("from"))
    destinations = normalize_destinations(row.get("to"))
    return ParsedRow(
        duration=duration,
        rooms=rooms,
        adults=adults,
        children=children,
        infants=infants,
        start_date=start_date,
        end_date=end_date,
        departure_airport=departure_airport,
        destinations=destinations,
    )


def read_rows(csv_path: Path) -> Iterator[ParsedRow]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield parse_row(row)


def init_counter_bundle() -> dict[str, Counter]:
    return {
        "duration": Counter(),
        "rooms": Counter(),
        "party": Counter(),
        "interval": Counter(),
        "airport": Counter(),
    }


def summarize_counter(
    counter: Counter,
    serializer: Callable[[object], object],
    top_n: int,
) -> dict[str, object]:
    if not counter:
        return {
            "mode": None,
            "mode_count": 0,
            "top_values": [],
            "unique_values": 0,
            "total": 0,
        }
    most_common = counter.most_common(top_n)
    mode_value, mode_count = most_common[0]
    return {
        "mode": serializer(mode_value),
        "mode_count": mode_count,
        "top_values": [{"value": serializer(value), "count": count} for value, count in most_common],
        "unique_values": len(counter),
        "total": sum(counter.values()),
    }


def serialize_party(value: tuple[int, int, int]) -> dict[str, int]:
    adults, children, infants = value
    return {"adults": adults, "children": children, "infants": infants}


def serialize_interval(value: tuple[str, str]) -> dict[str, str]:
    start, end = value
    return {"start": start, "end": end}


def build_statistics(rows: Iterable[ParsedRow], *, top_n: int) -> tuple[dict, dict, dict]:
    global_counters = init_counter_bundle()
    destination_counters: MutableMapping[str, dict[str, Counter]] = defaultdict(init_counter_bundle)
    intersection_counters: MutableMapping[tuple[str, ...], Counter] = defaultdict(Counter)
    processed_rows = 0
    destination_mentions = 0

    for parsed in rows:
        processed_rows += 1
        party = parsed.party_tuple
        interval = parsed.interval

        if parsed.duration is not None:
            global_counters["duration"][parsed.duration] += 1
        if parsed.rooms is None:
            global_counters["rooms"][None] += 1
        else:
            global_counters["rooms"][parsed.rooms] += 1
        global_counters["party"][party] += 1
        if interval:
            global_counters["interval"][interval] += 1
        if parsed.departure_airport:
            global_counters["airport"][parsed.departure_airport] += 1

        unique_destinations = sorted(set(parsed.destinations))
        destination_mentions += len(unique_destinations)
        for dest in unique_destinations:
            bundle = destination_counters[dest]
            if parsed.duration is not None:
                bundle["duration"][parsed.duration] += 1
            if parsed.rooms is None:
                bundle["rooms"][None] += 1
            else:
                bundle["rooms"][parsed.rooms] += 1
            bundle["party"][party] += 1
            if interval:
                bundle["interval"][interval] += 1
            if parsed.departure_airport:
                bundle["airport"][parsed.departure_airport] += 1

        if interval and len(unique_destinations) >= 2:
            combo = tuple(unique_destinations)
            intersection_counters[combo][interval] += 1

    global_summary = {
        "duration": summarize_counter(global_counters["duration"], lambda value: value, top_n),
        "rooms": summarize_counter(global_counters["rooms"], lambda value: value, top_n),
        "party": summarize_counter(global_counters["party"], serialize_party, top_n),
        "interval": summarize_counter(global_counters["interval"], serialize_interval, top_n),
        "departure_airport": summarize_counter(
            global_counters["airport"], lambda value: value, top_n
        ),
        "totals": {
            "rows": processed_rows,
            "destination_mentions": destination_mentions,
        },
    }

    destination_summary = {}
    for dest in sorted(destination_counters):
        bundle = destination_counters[dest]
        destination_summary[dest] = {
            "duration": summarize_counter(bundle["duration"], lambda value: value, top_n),
            "rooms": summarize_counter(bundle["rooms"], lambda value: value, top_n),
            "party": summarize_counter(bundle["party"], serialize_party, top_n),
            "interval": summarize_counter(bundle["interval"], serialize_interval, top_n),
            "departure_airport": summarize_counter(
                bundle["airport"], lambda value: value, top_n
            ),
        }

    intersection_summary = {}
    for combo in sorted(intersection_counters, key=lambda values: (len(values), values)):
        counter = intersection_counters[combo]
        summary = summarize_counter(counter, serialize_interval, top_n)
        intersection_summary["||".join(combo)] = {
            "destinations": list(combo),
            "mode": summary["mode"],
            "mode_count": summary["mode_count"],
            "top_intervals": summary["top_values"],
            "unique_intervals": summary["unique_values"],
            "total": summary["total"],
        }

    return global_summary, destination_summary, intersection_summary


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    rows = read_rows(csv_path)
    global_summary, destination_summary, intersection_summary = build_statistics(
        rows, top_n=args.top_n
    )

    metadata = {
        "schema_version": args.schema_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(csv_path),
            "sha256": compute_sha256(csv_path),
            "rows": global_summary["totals"]["rows"],
        },
        "top_n": args.top_n,
        "generator": "scripts.build_popularity_stats",
    }

    payload = {
        "metadata": metadata,
        "global": global_summary,
        "destinations": destination_summary,
        "intersections": intersection_summary,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        if args.pretty:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        else:
            json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
        handle.write("\n")

    print(
        f"Wrote popularity statistics to {output_path} (destinations={len(destination_summary)}, "
        f"rows={metadata['source']['rows']})"
    )


if __name__ == "__main__":
    main()
