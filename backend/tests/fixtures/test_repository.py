from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_PATH = REPO_ROOT / "backend" / "app" / "fixtures" / "repository.py"

spec = importlib.util.spec_from_file_location("fixtures_repository", REPOSITORY_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to import fixture repository module for testing")
_repository_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_repository_module)
FixtureRepository = _repository_module.FixtureRepository


def test_fixture_repository_loads_and_normalises_data() -> None:
    fixtures_dir = REPO_ROOT / "fixtures"
    repository = FixtureRepository(fixtures_dir)

    amsterdam = repository.get_airport_by_name("Amsterdam")
    assert amsterdam["id"] == "AMS"
    assert amsterdam["available"] is True

    brussels = repository.get_airport_by_name("brussels")
    assert brussels["id"] == "BRU"

    ams_by_id = repository.get_airport_by_id("ams")
    assert ams_by_id["name"] == "Amsterdam"

    italy = repository.get_destination_by_name("ItALy")
    assert italy["id"] == "d7b4bb39-123c-1234-b123-1234567i"

    italy_by_id = repository.get_destination_by_id("d7b4bb39-123c-1234-b123-1234567i")
    assert italy_by_id["name"] == "Italy"

    dates = repository.list_checkin_dates()
    assert dates  # non-empty
    assert dates == sorted(dates, key=lambda value: datetime.strptime(value, "%d-%m-%Y"))

    destination_synonyms = repository.locale_synonyms("destinations")
    assert destination_synonyms["nl"]["spanje"] == "d7b4bb39-123c-1234-1234-1234567s"


def test_fixture_repository_missing_file(tmp_path: Path) -> None:
    # Provide only a subset of fixtures to trigger the missing file handling.
    (tmp_path / "destinations.json").write_text(
        json.dumps({"data": {"countries": [{"id": "C1", "name": "Country"}]}}),
        encoding="utf-8",
    )
    (tmp_path / "dates.json").write_text(
        json.dumps({"data": {"dates": [{"date": "01-01-2025"}]}}),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        FixtureRepository(tmp_path)


def test_fixture_repository_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "airports.json").write_text("{not valid json", encoding="utf-8")
    (tmp_path / "destinations.json").write_text(
        json.dumps({"data": {"countries": [{"id": "C1", "name": "Country"}]}}),
        encoding="utf-8",
    )
    (tmp_path / "dates.json").write_text(
        json.dumps({"data": {"dates": [{"date": "01-01-2025"}]}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        FixtureRepository(tmp_path)
