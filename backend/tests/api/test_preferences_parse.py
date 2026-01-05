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
from backend.app.pipeline.preferences import PreferenceRunResult


class StubPreferencesPipeline:
    def run(self, text: str, method: str | None = None) -> PreferenceRunResult:
        return PreferenceRunResult(
            status="success",
            method_requested="rules",
            method_used="rules-basic",
            detection=LanguageDetectionResult(language="en", confidence=0.91),
            filters=[{"filterId": "wifi", "filterLabel": "Facilities", "options": []}],
            timings={"languageMs": 5.0, "totalMs": 1200.0},
            metadata={"methodType": "rules"},
            mappings=[{"filterId": "wifi", "spans": [{"text": "wifi"}]}],
            error=None,
        )


class StubNoPreferencesPipeline:
    def run(self, text: str, method: str | None = None) -> PreferenceRunResult:
        return PreferenceRunResult(
            status="no-preferences-detected",
            method_requested=None,
            method_used="rules-basic",
            detection=LanguageDetectionResult(language="en", confidence=0.51),
            filters=[],
            timings={"languageMs": 2.0, "totalMs": 25.0},
            metadata={},
            mappings=None,
            error=None,
        )


def test_preferences_parse_endpoint_formats_response(monkeypatch) -> None:
    monkeypatch.setenv("PROCESSING_THRESHOLD_MS", "1000")

    for cache in (
        get_settings,
        get_pipeline,
        get_llm_client,
        get_methods_catalog,
        get_preferences_pipeline,
    ):
        cache.cache_clear()

    app = create_app()
    app.dependency_overrides[get_preferences_pipeline] = lambda: StubPreferencesPipeline()
    client = TestClient(app)

    try:
        response = client.post(
            "/v1/preferences/parse",
            json={"text": "Need wifi", "mode": "preferences", "method": "rules"},
        )

        assert response.status_code == 200
        payload = response.json()

        assert payload["status"] == "success"
        assert payload["filters"] == [
            {"filterId": "wifi", "filterLabel": "Facilities", "options": []}
        ]

        metadata = payload["metadata"]
        assert metadata["mode"] == "preferences"
        assert metadata["method"] == "rules-basic"
        assert metadata["requestedMethod"] == "rules"
        assert metadata["language"] == {"code": "en", "confidence": 0.91}
        assert metadata["timings"]["thresholdBreached"] is True
        assert metadata["timings"]["totalMs"] == 1200.0
        assert metadata["mappings"] == [
            {"filterId": "wifi", "spans": [{"text": "wifi"}]}
        ]
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        get_pipeline.cache_clear()
        get_llm_client.cache_clear()
        get_methods_catalog.cache_clear()
        get_preferences_pipeline.cache_clear()


def test_preferences_parse_endpoint_maps_no_preferences_status(monkeypatch) -> None:
    for cache in (
        get_settings,
        get_pipeline,
        get_llm_client,
        get_methods_catalog,
        get_preferences_pipeline,
    ):
        cache.cache_clear()

    app = create_app()
    app.dependency_overrides[get_preferences_pipeline] = lambda: StubNoPreferencesPipeline()
    client = TestClient(app)

    try:
        response = client.post(
            "/v1/preferences/parse",
            json={"text": "Just browsing", "mode": "preferences"},
        )

        assert response.status_code == 200
        payload = response.json()

        assert payload["status"] == "failed"
        assert payload["filters"] == []

        metadata = payload["metadata"]
        assert metadata["statusReason"] == "no-preferences-detected"
        assert metadata["status"] == "failed"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        get_pipeline.cache_clear()
        get_llm_client.cache_clear()
        get_methods_catalog.cache_clear()
        get_preferences_pipeline.cache_clear()
