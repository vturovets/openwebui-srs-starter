from __future__ import annotations

from typing import Iterable

import pytest

from backend.tests.pipeline.test_pipeline_methods import pipeline_factory


@pytest.mark.parametrize(
    "utterance, expected_from, expected_dests",
    [
        (
            "Find me a trip in the southern hemisphere next June",
            {"code": "CRL", "name": "Charleroi"},
            {"Australia", "New Zealand", "Chile"},
        ),
        (
            "Find me a trip in the southern hemisphere next June from Ostend",
            {"code": "OST", "name": "Ostend"},
            {"Australia", "New Zealand", "Chile"},
        ),
    ],
)
@pytest.mark.parametrize("method", ["gemini-2.5-flash", "hybrid"])
def test_llm_based_southern_hemisphere_trips(
    pipeline_factory, method: str, utterance: str, expected_from: dict, expected_dests: set[str]
) -> None:
    llm_payloads = {
        utterance: {
            "airports": [expected_from["code"]] if expected_from["code"] == "OST" else [],
            "destinations": [
                "d7b4bb39-2000-1234-aaaa-1234567a",
                "d7b4bb39-2000-1234-aaaa-1234567b",
                "d7b4bb39-2000-1234-aaaa-1234567f",
            ],
            "dates": ["2026-06-01"],
            "duration": {"id": "2007"},
            "party": {"adults": 2, "nonAdults": 0},
            "rooms": 1,
        }
    }

    pipeline = pipeline_factory(llm_payloads)

    result = pipeline.run(utterance, method=method)

    assert result.status == "success"
    assert result.method_used in {"gemini-2.5-flash", "hybrid-v1", "rules-basic"}
    assert result.normalized is not None
    assert result.normalized.language == "en"
    assert result.normalized.from_codes == [expected_from["code"]]
    assert set(result.normalized.departure_dates) == {"2026-05-29", "2026-06-04"}
    assert result.normalized.duration_id == "2007"
    assert result.normalized.party == {"adults": 2, "nonAdults": 0}
    assert result.normalized.rooms == 1

    airport_names = {airport["name"] for airport in result.normalized.context.get("airports", [])}
    assert airport_names == {expected_from["name"]}

    destination_names = _dest_names(result.normalized.context.get("destinations", []))
    assert destination_names == expected_dests


@pytest.mark.parametrize(
    "utterance, expected_from",
    [
        (
            "Find me a trip in the southern hemisphere next June",
            {"code": "CRL", "name": "Charleroi"},
        ),
        (
            "Find me a trip in the southern hemisphere next June from Ostend",
            {"code": "OST", "name": "Ostend"},
        ),
    ],
)
def test_rules_basic_southern_hemisphere_trips(
    pipeline_factory, utterance: str, expected_from: dict
) -> None:
    pipeline = pipeline_factory()

    result = pipeline.run(utterance, method="rules-basic")

    assert result.status == "success"
    assert result.normalized is not None
    assert result.normalized.language == "en"
    assert result.normalized.from_codes == [expected_from["code"]]
    assert set(result.normalized.departure_dates) == {"2026-02-11", "2026-02-17"}
    assert result.normalized.duration_id == "2007"
    assert result.normalized.party == {"adults": 2, "nonAdults": 0}
    assert result.normalized.rooms == 1

    airport_names = {airport["name"] for airport in result.normalized.context.get("airports", [])}
    assert airport_names == {expected_from["name"]}

    destination_names = _dest_names(result.normalized.context.get("destinations", []))
    assert destination_names == {"Costa Rica"}


def _dest_names(destinations: Iterable[dict]) -> set[str]:
    return {dest.get("name", "") for dest in destinations if dest.get("name")}
