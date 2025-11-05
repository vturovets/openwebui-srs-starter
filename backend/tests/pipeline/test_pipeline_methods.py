from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from backend.app.config import Settings
from backend.app.pipeline.pipeline import HolidaySearchPipeline


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture()
def pipeline_factory(tmp_path: Path):
    """Provide a factory for creating pipelines with stub LLM responses."""

    def factory(responses: Mapping[str, Mapping[str, object]] | None = None) -> HolidaySearchPipeline:
        settings = Settings(fixtures_dir=FIXTURES_DIR, csv_path=tmp_path / "pipeline-log.csv")

        if responses is None:
            def llm_client(_: str) -> Mapping[str, object]:
                raise ValueError("LLM extractor is not configured for this pipeline instance")
        else:
            def llm_client(text: str) -> Mapping[str, object]:
                try:
                    return responses[text]
                except KeyError as exc:
                    raise ValueError(f"Unexpected LLM request for '{text}'") from exc

        return HolidaySearchPipeline(
            settings=settings,
            fixtures_dir=settings.fixtures_dir,
            llm_client=llm_client,
        )

    return factory


def test_pipeline_rules_only_success(pipeline_factory) -> None:
    pipeline = pipeline_factory()
    utterance = "Book a trip from Amsterdam to Italy on 10 October 2025 for 7 nights"

    result = pipeline.run(utterance, method="rules")

    assert result.status == "success"
    assert result.method_used == "rules"
    assert result.validation["status"] == "passed"
    assert "languageMs" in result.timings


def test_pipeline_hybrid_fallback_success(pipeline_factory) -> None:
    llm_payloads = {
        "Need a getaway from Amsterdam to Spain": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-123c-1234-b123-1234567i"],
            "dates": ["2025-11-25"],
        }
    }
    pipeline = pipeline_factory(llm_payloads)

    result = pipeline.run("Need a getaway from Amsterdam to Spain", method="hybrid")

    assert result.status == "success"
    assert result.method_used == "llm"
    assert result.validation["status"] == "passed"
    hybrid_meta = result.metadata.get("hybrid", {})
    assert hybrid_meta.get("fallbackTriggered") is True
    assert hybrid_meta.get("primaryFailure", "").startswith("Departure date is required")
    attempts = hybrid_meta.get("attempts", [])
    assert attempts and attempts[0]["method"] == "rules" and attempts[0]["status"] == "failed"


def test_pipeline_hybrid_fallback_failure(pipeline_factory) -> None:
    llm_payloads = {
        "Fallback still missing data": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-123c-1234-b123-1234567i"],
            "dates": [],
        }
    }
    pipeline = pipeline_factory(llm_payloads)

    result = pipeline.run("Fallback still missing data", method="hybrid")

    assert result.status == "failed"
    assert result.method_used == "llm"
    assert result.validation["status"] == "failed"
    hybrid_meta = result.metadata.get("hybrid", {})
    assert hybrid_meta.get("fallbackTriggered") is True
    attempts = hybrid_meta.get("attempts", [])
    assert len(attempts) == 2
    assert attempts[-1]["status"] == "failed"
