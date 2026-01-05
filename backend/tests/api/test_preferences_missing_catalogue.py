from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.dependencies import (
    get_llm_client,
    get_methods_catalog,
    get_pipeline,
    get_preferences_pipeline,
    get_settings,
)
from backend.app.main import create_app
from backend.app.pipeline.language import LanguageDetectionResult
from backend.app.pipeline.pipeline import PipelineRunResult


class StubHolidayPipeline:
    def run(self, text: str, method: str | None = None) -> PipelineRunResult:
        return PipelineRunResult(
            status="success",
            method_requested=method or "rules-basic",
            method_used="rules-basic",
            detection=LanguageDetectionResult(language="en", confidence=0.92),
            extraction=None,
            normalized=None,
            validation={},
            metadata={},
            attempts=[],
            timings={"totalMs": 5.0, "languageMs": 1.0},
            error=None,
        )


def test_missing_filters_catalogue_does_not_break_parse(monkeypatch, tmp_path) -> None:
    missing_catalogue = tmp_path / "filters_options.csv"
    monkeypatch.setenv("FILTERS_OPTIONS_PATH", str(missing_catalogue))

    for cache in (
        get_settings,
        get_pipeline,
        get_llm_client,
        get_methods_catalog,
        get_preferences_pipeline,
    ):
        cache.cache_clear()

    app = create_app()
    app.dependency_overrides[get_pipeline] = lambda: StubHolidayPipeline()
    client = TestClient(app)

    try:
        holiday_response = client.post(
            "/v1/parse",
            json={"text": "Plan a trip", "mode": "direct-parse"},
        )

        assert holiday_response.status_code == 200
        holiday_payload = holiday_response.json()
        assert holiday_payload["status"] == "success"

        preferences_response = client.post(
            "/v1/preferences/parse",
            json={"text": "Need wifi", "mode": "preferences"},
        )

        assert preferences_response.status_code == 200
        preferences_payload = preferences_response.json()
        assert preferences_payload["status"] == "failed"
        metadata = preferences_payload["metadata"]
        assert metadata["statusReason"] == "invalid-catalogue"
        assert "error" in metadata
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        get_pipeline.cache_clear()
        get_llm_client.cache_clear()
        get_methods_catalog.cache_clear()
        get_preferences_pipeline.cache_clear()
