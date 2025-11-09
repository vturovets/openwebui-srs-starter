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

    logger.log({"Timestamp": "now", "User Input": "hello"})
    logger.log({"Timestamp": "later", "Pipeline Status": "success"})

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)

    assert tuple(header) == CSV_LOG_FIELDS


def test_csv_logger_serialises_extended_columns(csv_path: Path) -> None:
    logger = CSVLogger(path=csv_path, fieldnames=CSV_LOG_FIELDS)

    payload = {
        "Timestamp": "now",
        "User Input": "hello",
        "Language Detection": ["en", "0.92"],
        "Missing Fields": ["from"],
        "Invalid Fields": ["party"],
        "Transcript": [{"role": "user", "text": "hello"}],
    }

    logger.log(payload)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    assert len(rows) == 2
    header, data_row = rows
    assert tuple(header) == CSV_LOG_FIELDS

    def index_for(field: str) -> int:
        return header.index(field)

    def indices_for(field: str) -> list[int]:
        return [index for index, value in enumerate(header) if value == field]

    language_indices = indices_for("Language Detection")
    assert data_row[language_indices[0]] == "en"
    assert data_row[language_indices[1]] == "0.92"
    assert json.loads(data_row[index_for("Missing Fields")]) == ["from"]
    assert json.loads(data_row[index_for("Invalid Fields")]) == ["party"]
    assert json.loads(data_row[index_for("Transcript")]) == [{"role": "user", "text": "hello"}]


def test_csv_logger_supports_custom_delimiter(csv_path: Path) -> None:
    logger = CSVLogger(path=csv_path, fieldnames=CSV_LOG_FIELDS, delimiter=";")

    logger.log({"Timestamp": "now", "User Input": "hello"})

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))

    assert len(rows) == 1
    assert rows[0]["User Input"] == "hello"


def test_utc_timestamp_includes_utc_indicator() -> None:
    timestamp = _utc_timestamp()

    assert timestamp.endswith("Z") or timestamp.endswith("+00:00")
