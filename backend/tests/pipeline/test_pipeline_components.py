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
from backend.app.logging import CSVLogger, ImportSummaryLogger, IMPORT_SUMMARY_LOG_FIELDS
from backend.app.api.routes import ParseRequest, parse_text
from backend.app.schemas import ImportSummary as ImportSummarySchema
from backend.app.pipeline.extractor_rules import ExtractionResult
from backend.app.pipeline import language as language_module
from backend.app.pipeline.language import LanguageDetector
from backend.app.pipeline.normalizer import Normalizer
from backend.app.pipeline.pipeline import (
    HolidaySearchPipeline,
    PipelineRunResult,
    SearchConfiguration,
)
from backend.app.pipeline.validator import ValidationError
from fastapi import HTTPException
from backend.app.services import import_runner
from backend.app.telemetry import resource_monitor


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
def app_dependencies(
    tmp_path: Path,
) -> Iterator[tuple[Settings, HolidaySearchPipeline, CSVLogger, ImportSummaryLogger]]:
    settings = Settings(
        fixtures_dir=FIXTURES_DIR,
        csv_path=tmp_path / "api-log.csv",
        import_summary_path=tmp_path / "import-summary.csv",
        allowed_langs=["en", "nl", "fr"],
    )
    pipeline = HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)
    logger = CSVLogger(
        path=settings.csv_path,
        fieldnames=CSV_LOG_FIELDS,
    )
    summary_logger = ImportSummaryLogger(
        path=settings.import_summary_path,
        fieldnames=IMPORT_SUMMARY_LOG_FIELDS,
    )
    yield settings, pipeline, logger, summary_logger


def test_language_detector_accepts_supported_language(pipeline: HolidaySearchPipeline) -> None:
    detection = pipeline.language_detector.detect("I am looking for a holiday in Japan")

    assert detection.language == "en"
    assert detection.confidence >= 0.5


def test_language_detector_handles_dutch_and_french(pipeline: HolidaySearchPipeline) -> None:
    dutch = pipeline.language_detector.detect("Ik zoek een vakantie naar Australie in oktober.")
    french = pipeline.language_detector.detect("Je cherche des vacances en Australie en octobre.")

    assert dutch.language == "nl"
    assert french.language == "fr"
    assert dutch.confidence > 0.0
    assert french.confidence > 0.0


def test_language_detector_disallows_missing_english() -> None:
    detector = LanguageDetector(["es"])

    with pytest.raises(ValueError):
        detector.detect("Looking for a holiday in Japan")


def test_language_detector_rejects_disallowed_language() -> None:
    detector = LanguageDetector(["en", "nl"])

    with pytest.raises(ValueError):
        detector.detect("Je voudrais des vacances en Australie")


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


def test_pipeline_imputes_unspecified_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POPULARITY_IMPUTER_ENABLED", "true")

    settings = Settings(
        fixtures_dir=FIXTURES_DIR,
        csv_path=tmp_path / "log.csv",
        allowed_langs=["en", "nl", "fr"],
    )
    pipeline = HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)

    result = pipeline.run("Show me the cheapest offers")

    assert result.status == "success"
    assert result.normalized is not None
    assert result.normalized.to_ids == ["d7b4bb39-2000-1234-aaab-1234567h:COUNTRY"]
    assert result.normalized.from_codes == ["CRL"]
    assert result.normalized.departure_dates == ["2026-02-11", "2026-02-17"]
    assert result.normalized.duration_id == "2007"
    assert result.normalized.party == {"adults": 2, "nonAdults": 0}
    imputed = result.metadata.get("imputed", {})
    assert imputed.get("to", {}).get("source") == "popularity"
    assert imputed.get("from", {}).get("source") == "destination:Costa Rica"
    assert imputed.get("departureDate", {}).get("source") == "destination:Costa Rica"
    assert imputed.get("durationId", {}).get("source") == "destination:Costa Rica"
    assert imputed.get("party", {}).get("source") == "destination:Costa Rica"
    assert imputed.get("rooms", {}).get("source") == "configuration"


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
            "Need a family holiday from Amsterdam to Japan on 10 October 2025 for 7 nights",
            "en",
            {"AMS"},
            {"d7b4bb39-2000-1234-aaac-1234567d"},
            "2007",
            None,
        ),
        (
            "Ik zoek een vakantie vanuit Amsterdam naar Australie op 10 oktober 2025 voor 7 nachten met +- 3 dagen flexibiliteit.",
            "nl",
            {"AMS"},
            {"d7b4bb39-2000-1234-aaaa-1234567a"},
            "2007",
            "3",
        ),
        (
            "Je cherche des vacances au départ de Ostende vers la Nouvelle-Zélande le 10 octobre 2025 pour 7 nuits avec +- 3 jours de flexibilité.",
            "fr",
            {"OST"},
            {"d7b4bb39-2000-1234-aaaa-1234567b"},
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
    utterance = "Plan a trip from Amsterdam to Japan on 10 October 2025 for a week"
    extraction = pipeline.extractor.extract(utterance, language="en")
    normalized = pipeline.normalizer.normalize("en", extraction)

    pipeline.validator.validate(normalized)


def test_validator_requires_departure_date(pipeline: HolidaySearchPipeline) -> None:
    utterance = "I am looking for a trip departing from Amsterdam or Ostend to Japan or Australia."
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

    assert "Destination is required" in str(exc.value)


def _run_pipeline_scenario(
    pipeline: HolidaySearchPipeline, utterance: str
) -> PipelineRunResult:
    result = pipeline.run(utterance)

    assert result.status == "success"
    assert result.validation["status"] == "passed"
    assert result.normalized is not None
    return result


def test_pipeline_imputes_single_destination_stats(pipeline: HolidaySearchPipeline) -> None:
    result = _run_pipeline_scenario(pipeline, "Best cheap hotels in Australia")

    extraction = result.extraction
    assert extraction is not None
    assert len(extraction.destinations) == 1

    metadata = result.metadata.get("imputed", {})
    assert metadata.get("departureDate", {}).get("source") == "destination:Australia"
    assert metadata.get("from", {}).get("source") == "destination:Australia"


def test_pipeline_imputes_multi_destination_without_intersection(
    pipeline: HolidaySearchPipeline,
) -> None:
    result = _run_pipeline_scenario(pipeline, "Cheapest offers for Kenya and Japan")

    extraction = result.extraction
    assert extraction is not None
    assert len(extraction.destinations) == 2

    metadata = result.metadata.get("imputed", {})
    assert metadata.get("departureDate", {}).get("source", "").startswith("intersection:")


def _call_parse(
    payload: ParseRequest,
    settings: Settings,
    pipeline: HolidaySearchPipeline,
    logger: CSVLogger,
    summary_logger: ImportSummaryLogger | None,
):
    return asyncio.run(
        parse_text(
            payload,
            settings=settings,
            pipeline=pipeline,
            logger=logger,
            summary_logger=summary_logger,
        )
    )


def test_parse_endpoint_success_logs_and_returns_payload(app_dependencies) -> None:
    settings, pipeline, logger, summary_logger = app_dependencies
    payload = ParseRequest(
        text="Book a trip from Amsterdam to Japan on 10 October 2025 for 7 nights",
        mode="dialog",
        method="sut",
    )

    response = _call_parse(payload, settings, pipeline, logger, summary_logger)

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


def test_parse_endpoint_import_mode_returns_summary(app_dependencies) -> None:
    settings, pipeline, logger, summary_logger = app_dependencies
    batch_payload = [
        {
            "text": "Book a family trip from Amsterdam to Japan on 10 October 2025 for 7 nights",
            "mode": "dialog",
            "method": "sut",
        },
        {
            "text": "Find holidays from Ostend to Australia in October",
            "mode": "direct-parse",
        },
    ]
    payload = ParseRequest(text="", import_mode=True, batch=batch_payload)

    response = _call_parse(payload, settings, pipeline, logger, summary_logger)

    assert isinstance(response, ImportSummarySchema)
    assert response.status in {"success", "partial"}
    assert response.counts.requests == len(batch_payload)
    assert response.latency.p50_ms is not None
    assert response.durations.job_ms >= 0.0
    assert response.durations.processing_ms >= 0.0
    assert response.resources.throttle_count >= 0

    with settings.import_summary_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    assert len(rows) == 2
    header, summary_row = rows
    assert header == list(IMPORT_SUMMARY_LOG_FIELDS)

    def index_for(field: str) -> int:
        return header.index(field)

    assert summary_row[index_for("Status")] == response.status
    assert summary_row[index_for("Requests")] == str(response.counts.requests)
    assert summary_row[index_for("Mode")] == (response.mode or "")


def test_parse_endpoint_supports_french_input(app_dependencies) -> None:
    settings, pipeline, logger, summary_logger = app_dependencies
    payload = ParseRequest(
        text=(
            "Je cherche des vacances au départ de Ostende vers l'Australie le 10 octobre 2025 "
            "pour 7 nuits avec +- 3 jours de flexibilité."
        ),
        mode="dialog",
    )

    response = _call_parse(payload, settings, pipeline, logger, summary_logger)

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
    settings, _, logger, summary_logger = app_dependencies
    failure_settings = Settings(
        fixtures_dir=settings.fixtures_dir,
        csv_path=settings.csv_path,
        import_summary_path=settings.import_summary_path,
        allowed_langs=settings.allowed_langs,
        popularity_imputer_enabled=False,
    )
    pipeline = HolidaySearchPipeline(
        settings=failure_settings,
        fixtures_dir=failure_settings.fixtures_dir,
    )
    payload = ParseRequest(
        text="I am looking for a trip starting on October 10 2025.",
    )

    response = _call_parse(payload, failure_settings, pipeline, logger, summary_logger)

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
