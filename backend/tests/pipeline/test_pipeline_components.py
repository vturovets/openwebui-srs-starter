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
from backend.app.dependencies import CSV_LOG_FIELDS
from backend.app.logging.csv_logger import CSVLogger
from backend.app.api.routes import ParseRequest, parse_text
from backend.app.pipeline.extractor_rules import ExtractionResult
from backend.app.pipeline import language as language_module
from backend.app.pipeline.language import LanguageDetector
from backend.app.pipeline.normalizer import Normalizer
from backend.app.pipeline.pipeline import HolidaySearchPipeline, SearchConfiguration
from backend.app.pipeline.validator import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture()
def pipeline(tmp_path: Path) -> HolidaySearchPipeline:
    settings = Settings(
        fixtures_dir=FIXTURES_DIR,
        csv_path=tmp_path / "log.csv",
        allowed_langs=["en", "nl", "fr"],
    )
    return HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)


@pytest.fixture()
def app_dependencies(tmp_path: Path) -> Iterator[tuple[Settings, HolidaySearchPipeline, CSVLogger]]:
    settings = Settings(
        fixtures_dir=FIXTURES_DIR,
        csv_path=tmp_path / "api-log.csv",
        allowed_langs=["en", "nl", "fr"],
    )
    pipeline = HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)
    logger = CSVLogger(
        path=settings.csv_path,
        fieldnames=CSV_LOG_FIELDS,
    )
    yield settings, pipeline, logger


def test_language_detector_accepts_supported_language(pipeline: HolidaySearchPipeline) -> None:
    detection = pipeline.language_detector.detect("I am looking for a holiday in Spain")

    assert detection.language == "en"
    assert detection.confidence >= 0.5


def test_language_detector_handles_dutch_and_french(pipeline: HolidaySearchPipeline) -> None:
    dutch = pipeline.language_detector.detect("Ik zoek een vakantie naar Spanje in oktober.")
    french = pipeline.language_detector.detect("Je cherche des vacances en Italie en octobre.")

    assert dutch.language == "nl"
    assert french.language == "fr"
    assert dutch.confidence > 0.0
    assert french.confidence > 0.0


def test_language_detector_disallows_missing_english() -> None:
    detector = LanguageDetector(["es"])

    with pytest.raises(ValueError):
        detector.detect("Looking for a holiday in Spain")


def test_language_detector_rejects_disallowed_language() -> None:
    detector = LanguageDetector(["en", "nl"])

    with pytest.raises(ValueError):
        detector.detect("Je voudrais des vacances en Italie")


def test_language_detector_recovers_from_misclassified_lang(monkeypatch) -> None:
    class Candidate:
        def __init__(self, lang: str, prob: float) -> None:
            self.lang = lang
            self.prob = prob

    detector = LanguageDetector(["en", "nl"])

    def fake_detect_langs(_: str):
        return [Candidate("sv", 0.95)]

    monkeypatch.setattr(language_module, "detect_langs", fake_detect_langs)
    detector._langdetect_available = True

    detection = detector.detect("The holiday trip is missing data")

    assert detection.language == "en"
    assert detection.confidence > 0.0


@pytest.mark.parametrize(
    (
        "utterance",
        "language",
        "expected_airports",
        "expected_destinations",
        "expected_duration",
        "expected_flex",
    ),
    [
        (
            "Need a family holiday from Amsterdam to Italy on 10 October 2025 for 7 nights",
            "en",
            {"AMS"},
            {"d7b4bb39-123c-1234-b123-1234567i"},
            "2007",
            None,
        ),
        (
            "Ik zoek een vakantie vanuit Amsterdam naar Spanje op 10 oktober 2025 voor 7 nachten met +- 3 dagen flexibiliteit.",
            "nl",
            {"AMS"},
            {"d7b4bb39-123c-1234-1234-1234567s"},
            "2007",
            "3",
        ),
        (
            "Je cherche des vacances au départ de Ostende vers l'Italie le 10 octobre 2025 pour 7 nuits avec +- 3 jours de flexibilité.",
            "fr",
            {"OST"},
            {"d7b4bb39-123c-1234-b123-1234567i"},
            "2007",
            "3",
        ),
    ],
)
def test_extractor_recognises_entities(
    pipeline: HolidaySearchPipeline,
    utterance: str,
    language: str,
    expected_airports: set[str],
    expected_destinations: set[str],
    expected_duration: str | None,
    expected_flex: str | None,
) -> None:
    extraction = pipeline.extractor.extract(utterance, language=language)

    assert {airport["id"] for airport in extraction.airports} == expected_airports
    assert {destination["id"] for destination in extraction.destinations} == expected_destinations
    if expected_duration is None:
        assert extraction.duration is None
    else:
        assert extraction.duration is not None
        assert extraction.duration["id"] == expected_duration
    if expected_flex is None:
        assert extraction.flexibility is None
    else:
        assert extraction.flexibility is not None
        assert extraction.flexibility["id"] == expected_flex
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
    extraction = pipeline.extractor.extract(utterance, language="en")
    normalized = pipeline.normalizer.normalize("en", extraction)

    pipeline.validator.validate(normalized)


def test_validator_requires_departure_date(pipeline: HolidaySearchPipeline) -> None:
    utterance = "I am looking for a trip departing from Amsterdam or Ostend to Spain or Italy."
    extraction = pipeline.extractor.extract(utterance, language="en")
    normalized = pipeline.normalizer.normalize("en", extraction)

    with pytest.raises(ValidationError) as exc:
        pipeline.validator.validate(normalized)

    assert "Departure date is required" in str(exc.value)


def test_validator_requires_departure_or_destination_with_date(pipeline: HolidaySearchPipeline) -> None:
    utterance = "I am looking for a trip starting on October 10 2025."
    extraction = pipeline.extractor.extract(utterance, language="en")
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
    recognized = response.metadata["recognizedEntities"]
    assert recognized["airports"] == ["AMS"]
    assert recognized["destinations"]
    assert recognized["dates"]
    assert response.metadata["missingFields"] == []
    assert response.metadata["invalidFields"] == []

    with settings.csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    assert len(rows) == 2
    header, log_entry = rows

    def index_for(field: str) -> int:
        return header.index(field)

    def indices_for(field: str) -> list[int]:
        return [index for index, value in enumerate(header) if value == field]

    timings = response.metadata["timings"]
    language_columns = indices_for("Language Detection")

    assert log_entry[index_for("User input")].startswith("Book a trip")
    assert log_entry[index_for("Request type")] == "Text"
    assert log_entry[index_for("Pipeline Status")] == "Success"
    assert log_entry[index_for("Method")] == "rules-basic"
    assert log_entry[index_for("Interaction Mode")] == "dialog"
    assert float(log_entry[language_columns[0]]) >= 0.0
    assert "en" in log_entry[language_columns[1]]
    assert log_entry[index_for("Processing Time")] == f"{timings.get('totalMs', 0.0):.2f}"
    output_payload = json.loads(log_entry[index_for("Output")])
    assert output_payload["status"] == "success"


def test_parse_endpoint_supports_french_input(app_dependencies) -> None:
    settings, pipeline, logger = app_dependencies
    payload = ParseRequest(
        text=(
            "Je cherche des vacances au départ de Ostende vers l'Italie le 10 octobre 2025 "
            "pour 7 nuits avec +- 3 jours de flexibilité."
        ),
        mode="dialog",
    )

    response = _call_parse(payload, settings, pipeline, logger)

    assert response.status == "success"
    assert response.data["language"] == "fr"
    assert response.metadata["language"]["code"] == "fr"

    with settings.csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    assert len(rows) == 2
    header, log_entry = rows

    def indices_for(field: str) -> list[int]:
        return [index for index, value in enumerate(header) if value == field]

    language_columns = indices_for("Language Detection")
    assert "fr" in log_entry[language_columns[1]]
    output_payload = json.loads(log_entry[header.index("Output")])
    assert output_payload["status"] == "success"
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
    assert set(response.metadata["missingFields"]) >= {"from", "to"}

    with settings.csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    assert len(rows) == 2
    header, log_entry = rows

    def index_for(field: str) -> int:
        return header.index(field)

    assert log_entry[index_for("Pipeline Status")] == "Failed"
    assert "Utterance" in log_entry[index_for("Output")]

    parsed_output = json.loads(log_entry[index_for("Output")])
    assert parsed_output["status"] == "failed"
    assert parsed_output["data"]["language"] == "en"
    assert parsed_output["validation"]["errors"][0]["message"].startswith("Utterance must include")
