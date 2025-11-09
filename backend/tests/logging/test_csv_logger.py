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

    logger.log({"Timestamp (UTC)": "now", "User input": "hello"})
    logger.log({"Timestamp (UTC)": "later", "Pipeline Status": "Success"})

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)

    assert tuple(header) == CSV_LOG_FIELDS


def test_csv_logger_serialises_extended_columns(csv_path: Path) -> None:
    logger = CSVLogger(path=csv_path, fieldnames=CSV_LOG_FIELDS)

    payload = {
        "Timestamp (UTC)": "now",
        "User input": "hello",
        "Language Detection": ["12.30", "en (0.92)"],
        "Output": {"status": "success"},
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
    assert data_row[language_indices[0]] == "12.30"
    assert data_row[language_indices[1]] == "en (0.92)"
    assert json.loads(data_row[index_for("Output")]) == {"status": "success"}


def test_csv_logger_supports_custom_delimiter(csv_path: Path) -> None:
    logger = CSVLogger(path=csv_path, fieldnames=CSV_LOG_FIELDS, delimiter=";")

    logger.log({"Timestamp (UTC)": "now", "User input": "hello"})

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))

    assert len(rows) == 1
    assert rows[0]["User input"] == "hello"


def test_utc_timestamp_includes_utc_indicator() -> None:
    timestamp = _utc_timestamp()

    assert timestamp.endswith("Z") or timestamp.endswith("+00:00")
