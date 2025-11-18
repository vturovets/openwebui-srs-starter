from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.pipeline.configuration import SearchConfiguration
from backend.app.services.popularity_imputer import PopularityImputer


@pytest.fixture(scope="module")
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "fixtures"


@pytest.fixture(scope="module")
def search_configuration(fixtures_dir: Path) -> SearchConfiguration:
    payload = json.loads((fixtures_dir / "configuration_search.json").read_text())
    return SearchConfiguration.from_fixture_payload(payload)


@pytest.fixture()
def popularity_settings(fixtures_dir: Path) -> Settings:
    return Settings(
        FIXTURES_DIR=str(fixtures_dir),
        POPULARITY_DATA_PATH=str(fixtures_dir / "popularity_stats.json"),
        POPULARITY_IMPUTER_ENABLED=True,
    )


def build_imputer(settings: Settings, configuration: SearchConfiguration) -> PopularityImputer:
    return PopularityImputer(settings=settings, configuration=configuration)


def test_impute_infers_global_defaults(popularity_settings: Settings, search_configuration: SearchConfiguration) -> None:
    imputer = build_imputer(popularity_settings, search_configuration)
    params = {"from": [], "to": [], "party": {}, "rooms": None, "departureDate": []}

    enriched, metadata = imputer.impute(params)

    assert enriched["durationId"] == "2007"
    assert enriched["party"] == {"adults": 2, "nonAdults": 0}
    assert enriched["rooms"] is None
    assert enriched["from"] == ["Charleroi"]
    assert enriched["departureDate"] == ["2026-02-19"]
    assert metadata["imputed"]["durationId"]["source"] == "global"
    assert metadata["imputed"]["rooms"]["autoRoomAllocationSwitch"] is True


def test_impute_prefers_single_destination_stats(popularity_settings: Settings, search_configuration: SearchConfiguration) -> None:
    imputer = build_imputer(popularity_settings, search_configuration)
    params = {"from": [], "to": ["Costa Rica"], "departureDate": []}

    enriched, metadata = imputer.impute(params)

    assert enriched["departureDate"] == ["2026-02-19"]
    assert metadata["imputed"]["departureDate"]["source"] == "destination:Costa Rica"
    assert metadata["imputed"]["from"]["source"] == "destination:Costa Rica"


def test_impute_uses_multi_destination_intersection(popularity_settings: Settings, search_configuration: SearchConfiguration) -> None:
    imputer = build_imputer(popularity_settings, search_configuration)
    params = {"from": [], "to": ["Costa Rica", "Kenya"], "departureDate": []}

    enriched, metadata = imputer.impute(params)

    assert enriched["departureDate"] == ["2025-12-11"]
    assert metadata["imputed"]["departureDate"]["source"] == "intersection:Costa Rica||Kenya"


def test_impute_falls_back_to_global_when_intersection_missing(popularity_settings: Settings, search_configuration: SearchConfiguration) -> None:
    imputer = build_imputer(popularity_settings, search_configuration)
    params = {"from": [], "to": ["Australia", "Japan"], "departureDate": []}

    enriched, metadata = imputer.impute(params)

    assert enriched["departureDate"] == ["2026-02-19"]
    assert metadata["imputed"]["departureDate"]["source"] == "global"


def test_imputer_logs_missing_destination(popularity_settings: Settings, search_configuration: SearchConfiguration, caplog: pytest.LogCaptureFixture) -> None:
    imputer = build_imputer(popularity_settings, search_configuration)
    caplog.set_level(logging.WARNING)
    params = {"from": [], "to": ["Atlantis"], "departureDate": []}

    enriched, metadata = imputer.impute(params)

    assert enriched["departureDate"] == ["2026-02-19"]
    assert metadata["destinationsWithoutStats"] == ["Atlantis"]
    assert any("Atlantis" in record.message for record in caplog.records)
