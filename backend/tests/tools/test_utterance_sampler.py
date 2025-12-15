from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from tools.utterance_generator.sampler import (
    load_multi_combos,
    load_single_utterances,
    sample_multi_rows,
    sample_single_rows,
    sample_to_csv,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_and_sample_single_dataset(tmp_path: Path) -> None:
    single_payload = {
        "results": [
            {
                "filterId": "F1",
                "filterName": "Filter 1",
                "optionId": "O1",
                "optionName": "Option 1",
                "utterances": [
                    {"utterance": "First option easy"},
                    {"utterance": "First option medium"},
                ],
            },
            {
                "filterId": "F2",
                "filterName": "Filter 2",
                "optionId": "O2",
                "optionName": "Option 2",
                "utterances": [
                    {"utterance": "Second option"},
                ],
            },
        ]
    }
    single_path = tmp_path / "single.json"
    _write_json(single_path, single_payload)

    rows = load_single_utterances(single_path)
    assert len(rows) == 3
    rng = random.Random(7)
    sampled = sample_single_rows(rows, 2, rng)
    assert len(sampled) == 2
    assert {row.filterId for row in sampled} <= {"F1", "F2"}
    assert all(row.optionName for row in sampled)


def test_sample_multi_rows_preserves_combo_matches(tmp_path: Path) -> None:
    multi_payload = {
        "results": [
            {
                "utterance": "blend first and second",
                "matched": [
                    {"filterId": "F1", "filterName": "Filter 1", "optionId": "O1", "optionName": "Option 1"},
                    {"filterId": "F2", "filterName": "Filter 2", "optionId": "O2", "optionName": "Option 2"},
                ],
            },
            {
                "utterance": "just third",
                "matched": [
                    {"filterId": "F3", "filterName": "Filter 3", "optionId": "O3", "optionName": "Option 3"},
                ],
            },
        ]
    }
    multi_path = tmp_path / "multi.json"
    _write_json(multi_path, multi_payload)

    combos = load_multi_combos(multi_path)
    assert len(combos) == 2

    rng = random.Random(3)
    expected_index = random.Random(3).sample(range(len(combos)), 1)[0]
    sampled_rows = sample_multi_rows(combos, 1, rng)
    assert len(sampled_rows) == len(combos[expected_index]["matched"])
    assert {row.utterance for row in sampled_rows} == {combos[expected_index]["utterance"]}
    assert {row.filterName for row in sampled_rows} == {
        match.get("filterName") for match in combos[expected_index]["matched"]
    }


def test_sample_to_csv_combines_sources(tmp_path: Path) -> None:
    single_path = tmp_path / "single.json"
    _write_json(
        single_path,
        {
            "results": [
                {
                    "filterId": "F1",
                    "filterName": "Filter 1",
                    "optionId": "O1",
                    "optionName": "Option 1",
                    "utterances": [
                        {"utterance": "alpha"},
                        {"utterance": "beta"},
                    ],
                }
            ]
        },
    )
    multi_path = tmp_path / "multi.json"
    _write_json(
        multi_path,
        {
            "results": [
                {
                    "utterance": "combo example",
                    "matched": [
                        {
                            "filterId": "F2",
                            "filterName": "Filter 2",
                            "optionId": "O2",
                            "optionName": "Option 2",
                        },
                    ],
                }
            ]
        },
    )

    output_path = tmp_path / "out.csv"
    rows = sample_to_csv(
        output_path=output_path,
        single_path=single_path,
        single_count=1,
        multi_path=multi_path,
        multi_count=1,
        seed=11,
    )

    assert output_path.exists()
    with output_path.open("r", encoding="utf-8") as handle:
        written_rows = list(csv.DictReader(handle))
    assert len(written_rows) == len(rows) == 2
    assert {row["filterId"] for row in written_rows} == {"F1", "F2"}
    assert {row["Utterance"] for row in written_rows} <= {"alpha", "beta", "combo example"}
    assert all(row.get("filterName") for row in written_rows)
