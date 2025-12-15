from __future__ import annotations

import csv
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

logger = logging.getLogger(__name__)


@dataclass
class SampledUtterance:
    utterance: str
    filterId: str
    filterName: str
    optionId: str
    optionName: str


def _load_json_results(path: Path) -> Sequence[dict]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and "results" in payload:
        results = payload.get("results") or []
    elif isinstance(payload, list):
        results = payload
    else:
        raise ValueError("Unexpected dataset shape; expected an object with results or an array")
    return list(results)


def load_single_utterances(path: Path) -> List[SampledUtterance]:
    results = _load_json_results(path)
    rows: List[SampledUtterance] = []
    for entry in results:
        filter_id = str(entry.get("filterId", "")).strip()
        filter_name = str(entry.get("filterName", "")).strip()
        option_id = str(entry.get("optionId", "")).strip()
        option_name = str(entry.get("optionName", "")).strip()
        for utterance_entry in entry.get("utterances", []) or []:
            utterance_text = str(utterance_entry.get("utterance", "")).strip()
            if not utterance_text:
                continue
            rows.append(
                SampledUtterance(
                    utterance=utterance_text,
                    filterId=filter_id,
                    filterName=filter_name,
                    optionId=option_id,
                    optionName=option_name,
                )
            )
    return rows


def load_multi_combos(path: Path) -> List[dict]:
    results = _load_json_results(path)
    combos: List[dict] = []
    for entry in results:
        utterance = str(entry.get("utterance", "")).strip()
        if not utterance:
            continue
        matched = entry.get("matched", []) or []
        combos.append({"utterance": utterance, "matched": list(matched)})
    return combos


def _sample_sequence(items: Sequence[object], sample_size: int, rng: random.Random) -> List[object]:
    if sample_size <= 0 or not items:
        return []
    if sample_size >= len(items):
        return list(items)
    return rng.sample(list(items), sample_size)


def sample_single_rows(rows: Sequence[SampledUtterance], count: int, rng: random.Random) -> List[SampledUtterance]:
    return list(_sample_sequence(rows, count, rng))


def sample_multi_rows(combos: Sequence[dict], count: int, rng: random.Random) -> List[SampledUtterance]:
    sampled_combos = _sample_sequence(combos, count, rng)
    rows: List[SampledUtterance] = []
    for combo in sampled_combos:
        utterance = combo.get("utterance", "")
        matched_entries = combo.get("matched", []) or []
        for match in matched_entries:
            rows.append(
                SampledUtterance(
                    utterance=utterance,
                    filterId=str(match.get("filterId", "")).strip(),
                    filterName=str(match.get("filterName", "")).strip(),
                    optionId=str(match.get("optionId", "")).strip(),
                    optionName=str(match.get("optionName", "")).strip(),
                )
            )
    return rows


def write_csv(rows: Sequence[SampledUtterance], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Utterance", "filterId", "filterName", "optionId", "optionName"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Utterance": row.utterance,
                    "filterId": row.filterId,
                    "filterName": row.filterName,
                    "optionId": row.optionId,
                    "optionName": row.optionName,
                }
            )
    logger.info("Wrote %s utterances to %s", len(rows), output_path)


def sample_to_csv(
    output_path: Path,
    *,
    single_path: Path | None = None,
    single_count: int = 0,
    multi_path: Path | None = None,
    multi_count: int = 0,
    seed: int | None = None,
) -> List[SampledUtterance]:
    rng = random.Random(seed)
    aggregated: List[SampledUtterance] = []

    if single_path:
        single_rows = load_single_utterances(single_path)
        aggregated.extend(sample_single_rows(single_rows, single_count, rng))
    if multi_path:
        multi_combos = load_multi_combos(multi_path)
        aggregated.extend(sample_multi_rows(multi_combos, multi_count, rng))

    write_csv(aggregated, output_path)
    return aggregated
