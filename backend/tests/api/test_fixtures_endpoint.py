"""Tests ensuring the fixtures endpoint exposes configuration flags."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pathlib import Path

from backend.app.dependencies import get_llm_client, get_methods_catalog, get_pipeline, get_settings
from backend.app.main import create_app


def test_fixtures_endpoint_includes_voice_configuration(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("INTERACTION_MODE", "dialog")
    monkeypatch.setenv("LLM_METHOD", "rules")
    monkeypatch.setenv("IMPORT_P95_THRESHOLD_MS", "2500")
    monkeypatch.setenv("IMPORT_P95_SAMPLE_SIZE", "1500")
    monkeypatch.setenv("IMPORT_P95_SIGNIFICANCE", "0.9")

    for cache in (get_settings, get_pipeline, get_llm_client, get_methods_catalog):
        cache.cache_clear()

    app = create_app()
    client = TestClient(app)

    try:
        response = client.get("/v1/fixtures")
        assert response.status_code == 200

        payload = response.json()
        assert payload["voiceEnabled"] is True
        assert payload["showFailedOnly"] is True
        assert payload["mode"] == "dialog"
        assert payload["llmMethod"] == "rules-basic"
        assert payload["llmMethodAlias"] == "rules"
        assert isinstance(payload["availableMethods"], list)
        assert payload["defaultMethod"] == "rules-basic"
        assert isinstance(payload["methodDefaults"], dict)
        performance_targets = payload["performanceTargets"]
        assert performance_targets == {
            "importP95ThresholdMs": 2500,
            "importP95SampleSize": 1500,
            "importP95Significance": 0.9,
        }
    finally:
        get_settings.cache_clear()
        get_pipeline.cache_clear()
        get_llm_client.cache_clear()
        get_methods_catalog.cache_clear()


def test_fixtures_endpoint_uses_default_performance_targets(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("FIXTURES_DIR", str(repo_root / "fixtures"))
    monkeypatch.setenv("CSV_PATH", str(tmp_path / "import-log.csv"))

    for cache in (get_settings, get_pipeline, get_llm_client, get_methods_catalog):
        cache.cache_clear()

    app = create_app()
    client = TestClient(app)

    try:
        response = client.get("/v1/fixtures")
        assert response.status_code == 200

        payload = response.json()
        performance_targets = payload["performanceTargets"]
        assert performance_targets == {
            "importP95ThresholdMs": 750,
            "importP95SampleSize": 1000,
            "importP95Significance": 0.95,
        }
    finally:
        get_settings.cache_clear()
        get_pipeline.cache_clear()
        get_llm_client.cache_clear()
        get_methods_catalog.cache_clear()
