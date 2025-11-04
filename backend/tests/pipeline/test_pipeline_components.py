"""Tests covering the NLP pipeline components end-to-end."""

from __future__ import annotations

import csv
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pytest
import asyncio

from backend.app.config import Settings
from backend.app.logging.csv_logger import CSVLogger
from backend.app.api.routes import ParseRequest, parse_text
from backend.app.pipeline.extractor_rules import ExtractionResult
from backend.app.pipeline.language import LanguageDetector
from backend.app.pipeline.normalizer import Normalizer
from backend.app.pipeline.pipeline import HolidaySearchPipeline, SearchConfiguration
from backend.app.pipeline.validator import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture()
def pipeline(tmp_path: Path) -> HolidaySearchPipeline:
    settings = Settings(fixtures_dir=FIXTURES_DIR, csv_path=tmp_path / "log.csv")
    return HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)


@pytest.fixture()
def app_dependencies(tmp_path: Path) -> Iterator[tuple[Settings, HolidaySearchPipeline, CSVLogger]]:
    settings = Settings(fixtures_dir=FIXTURES_DIR, csv_path=tmp_path / "api-log.csv")
    pipeline = HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)
    logger = CSVLogger(
        path=settings.csv_path,
        fieldnames=(
            "Timestamp",
            "Input",
            "Language",
            "Method",
            "STT",
            "ProcessingTime",
            "Output",
            "Status",
            "ThresholdBreached",
        ),
    )
    yield settings, pipeline, logger


def test_language_detector_accepts_supported_language(pipeline: HolidaySearchPipeline) -> None:
    detection = pipeline.language_detector.detect("I am looking for a holiday in Spain")

    assert detection.language == "en"
    assert detection.confidence >= 0.5


def test_language_detector_disallows_missing_english() -> None:
    detector = LanguageDetector(["es"])

    with pytest.raises(ValueError):
        detector.detect("Looking for a holiday in Spain")


@pytest.mark.parametrize(
    "utterance",
    [
        "Need a family holiday from Amsterdam to Italy on 10 October 2025 for 7 nights",
        "Looking to travel from Ostend to Spain around October 11 2025 for +- 3 days",
    ],
)
def test_extractor_recognises_entities(pipeline: HolidaySearchPipeline, utterance: str) -> None:
    extraction = pipeline.extractor.extract(utterance)

    assert {airport["id"] for airport in extraction.airports} <= {"AMS", "OST"}
    assert {destination["id"] for destination in extraction.destinations} <= {
        "d7b4bb39-123c-1234-b123-1234567i",
        "d7b4bb39-123c-1234-1234-1234567s",
    }
    assert extraction.duration is None or extraction.duration["id"] in {"2007", "2003", "2008"}
    assert extraction.has_dates()


def _make_extraction_with_date(date: datetime, flex_id: str | None = None) -> ExtractionResult:
    result = ExtractionResult(
        dates=[("provided", date)],
    )
    if flex_id is not None:
        result.flexibility = {"id": flex_id, "name": "custom"}
    return result


def test_normalizer_expands_flex_window(pipeline: HolidaySearchPipeline) -> None:
    extraction = _make_extraction_with_date(datetime(2025, 10, 12), flex_id="3")

    normalized = pipeline.normalizer.normalize("en", extraction)

    assert normalized.departure_dates == ["2025-10-09", "2025-10-15"]
    assert normalized.context["flex_option"]["id"] == "3"


def test_normalizer_handles_invalid_flex_identifier(pipeline: HolidaySearchPipeline) -> None:
    extraction = _make_extraction_with_date(datetime(2025, 10, 12), flex_id="not-a-number")

    normalized = pipeline.normalizer.normalize("en", extraction)

    assert normalized.departure_dates == ["2025-10-12"]


def test_normalizer_respects_disabled_flexibility(pipeline: HolidaySearchPipeline) -> None:
    raw_config = deepcopy(pipeline.configuration.raw)
    raw_config["flexibility"]["isFlexibleAllowed"] = False
    config = SearchConfiguration(raw=raw_config)
    normalizer = Normalizer(config)
    extraction = _make_extraction_with_date(datetime(2025, 10, 12), flex_id="3")

    normalized = normalizer.normalize("en", extraction)

    assert normalized.departure_dates == ["2025-10-12"]
    assert normalized.context["flex_option"] is None


def test_normalizer_preserves_iso_for_unavailable_date(pipeline: HolidaySearchPipeline) -> None:
    extraction = _make_extraction_with_date(datetime(2024, 1, 1))

    normalized = pipeline.normalizer.normalize("en", extraction)

    assert normalized.departure_dates == ["2024-01-01"]
    assert normalized.context["dates_base"].isoformat() == "2024-01-01"


def test_validator_accepts_required_field_combination(pipeline: HolidaySearchPipeline) -> None:
    utterance = "Plan a trip from Amsterdam to Spain on 10 October 2025 for a week"
    extraction = pipeline.extractor.extract(utterance)
    normalized = pipeline.normalizer.normalize("en", extraction)

    pipeline.validator.validate(normalized)


def test_validator_requires_departure_date(pipeline: HolidaySearchPipeline) -> None:
    utterance = "I am looking for a trip departing from Amsterdam or Ostend to Spain or Italy."
    extraction = pipeline.extractor.extract(utterance)
    normalized = pipeline.normalizer.normalize("en", extraction)

    with pytest.raises(ValidationError) as exc:
        pipeline.validator.validate(normalized)

    assert "Departure date is required" in str(exc.value)


def test_validator_requires_departure_or_destination_with_date(pipeline: HolidaySearchPipeline) -> None:
    utterance = "I am looking for a trip starting on October 10 2025."
    extraction = pipeline.extractor.extract(utterance)
    normalized = pipeline.normalizer.normalize("en", extraction)

    with pytest.raises(ValidationError) as exc:
        pipeline.validator.validate(normalized)

    assert "Utterance must include departure date" in str(exc.value)


def _call_parse(
    payload: ParseRequest,
    settings: Settings,
    pipeline: HolidaySearchPipeline,
    logger: CSVLogger,
):
    return asyncio.run(parse_text(payload, settings=settings, pipeline=pipeline, logger=logger))


def test_parse_endpoint_success_logs_and_returns_payload(app_dependencies) -> None:
    settings, pipeline, logger = app_dependencies
    payload = ParseRequest(
        text="Book a trip from Amsterdam to Italy on 10 October 2025 for 7 nights",
        mode="dialog",
        method="sut",
    )

    response = _call_parse(payload, settings, pipeline, logger)

    assert response.status == "success"
    assert response.data["from"] == ["AMS"]
    assert response.metadata["validation"]["status"] == "passed"

    with settings.csv_path.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    log_entry = rows[0]
    assert log_entry["Input"].startswith("Book a trip")
    assert log_entry["Language"] == "en"
    assert log_entry["Status"] == "success"
    expected_threshold = "true" if response.metadata["timings"]["thresholdBreached"] else "false"
    assert log_entry["ThresholdBreached"] == expected_threshold


def test_parse_endpoint_failure_logs_validation_errors(app_dependencies) -> None:
    settings, pipeline, logger = app_dependencies
    payload = ParseRequest(
        text="I am looking for a trip starting on October 10 2025.",
    )

    response = _call_parse(payload, settings, pipeline, logger)

    assert response.status == "failed"
    assert response.metadata["validation"]["status"] == "failed"
    assert response.metadata["validation"]["errors"]
    assert response.metadata["validation"]["errors"][0]["message"].startswith(
        "Utterance must include"
    )

    with settings.csv_path.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    log_entry = rows[0]
    assert log_entry["Status"] == "failed"
    expected_threshold = "true" if response.metadata["timings"]["thresholdBreached"] else "false"
    assert log_entry["ThresholdBreached"] == expected_threshold
    assert "Utterance" in log_entry["Output"]

    parsed_output = json.loads(log_entry["Output"])
    assert parsed_output["status"] == "failed"
    assert parsed_output["data"]["language"] == "en"
    assert parsed_output["validation"]["errors"][0]["message"].startswith("Utterance must include")
