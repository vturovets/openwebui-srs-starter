"""Regression tests for the CSV logging helper."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from backend.app.api.routes import _utc_timestamp
from backend.app.dependencies import CSV_LOG_FIELDS
from backend.app.logging.csv_logger import CSVLogger


@pytest.fixture()
def csv_path(tmp_path: Path) -> Path:
    return tmp_path / "events.csv"


def test_csv_logger_writes_configured_header(csv_path: Path) -> None:
    logger = CSVLogger(path=csv_path, fieldnames=CSV_LOG_FIELDS)

    logger.log({"Timestamp": "now", "Input": "hello"})
    logger.log({"Timestamp": "later", "Status": "success"})

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)

    assert tuple(header) == CSV_LOG_FIELDS


def test_csv_logger_serialises_extended_columns(csv_path: Path) -> None:
    logger = CSVLogger(path=csv_path, fieldnames=CSV_LOG_FIELDS)

    payload = {
        "Timestamp": "now",
        "MissingFields": ["from"],
        "InvalidFields": ["party"],
        "RecognizedAirports": ["AMS"],
        "RecognizedDestinations": ["DEST"],
        "RecognizedDates": ["2025-10-10T00:00:00"],
        "RecognizedDuration": "2007",
        "RecognizedFlexibility": "3",
    }

    logger.log(payload)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    row = rows[0]
    assert json.loads(row["MissingFields"]) == ["from"]
    assert json.loads(row["InvalidFields"]) == ["party"]
    assert json.loads(row["RecognizedAirports"]) == ["AMS"]
    assert json.loads(row["RecognizedDestinations"]) == ["DEST"]
    assert json.loads(row["RecognizedDates"]) == ["2025-10-10T00:00:00"]
    assert row["RecognizedDuration"] == "2007"
    assert row["RecognizedFlexibility"] == "3"


def test_csv_logger_supports_custom_delimiter(csv_path: Path) -> None:
    logger = CSVLogger(path=csv_path, fieldnames=CSV_LOG_FIELDS, delimiter=";")

    logger.log({"Timestamp": "now", "Input": "hello"})

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))

    assert len(rows) == 1
    assert rows[0]["Input"] == "hello"


def test_utc_timestamp_includes_utc_indicator() -> None:
    timestamp = _utc_timestamp()

    assert timestamp.endswith("Z") or timestamp.endswith("+00:00")
