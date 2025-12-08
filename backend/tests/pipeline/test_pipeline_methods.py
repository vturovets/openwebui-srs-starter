from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Mapping

import pytest

from backend.app.config import Settings
from backend.app.pipeline.pipeline import HolidaySearchPipeline


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture()
def pipeline_factory(tmp_path: Path):
    """Provide a factory for creating pipelines with stub LLM responses."""

    def factory(
        responses: Mapping[str, Mapping[str, object] | tuple[Mapping[str, object], float]]
        | None = None,
        *,
        allowed_langs: list[str] | None = None,
        methods_config_path: Path | None = None,
        default_method: str | None = None,
        popularity_imputer_enabled: bool | None = None,
    ) -> HolidaySearchPipeline:
        settings_kwargs: dict[str, object] = {
            "fixtures_dir": FIXTURES_DIR,
            "csv_path": tmp_path / "pipeline-log.csv",
            "allowed_langs": list(allowed_langs or ["en", "nl", "fr"]),
        }
        if methods_config_path is not None:
            settings_kwargs["methods_config_path"] = methods_config_path
        if default_method is not None:
            settings_kwargs["llm_method"] = default_method
        if popularity_imputer_enabled is not None:
            settings_kwargs["popularity_imputer_enabled"] = popularity_imputer_enabled
        settings = Settings(**settings_kwargs)

        if responses is None:
            def llm_client(_: str) -> Mapping[str, object]:
                raise ValueError("LLM extractor is not configured for this pipeline instance")
        else:
            def llm_client(text: str) -> Mapping[str, object]:
                try:
                    payload = responses[text]
                except KeyError as exc:
                    raise ValueError(f"Unexpected LLM request for '{text}'") from exc

                delay: float | None = None
                if isinstance(payload, tuple):
                    payload, delay = payload

                if delay:
                    sleep(delay)

                return payload

        return HolidaySearchPipeline(
            settings=settings,
            fixtures_dir=settings.fixtures_dir,
            llm_client=llm_client,
            methods_catalog=settings.load_methods_catalog(),
        )

    return factory


def test_pipeline_rules_only_success(pipeline_factory) -> None:
    pipeline = pipeline_factory()
    utterance = "Book a trip from Amsterdam to Japan on 10 October 2025 for 7 nights"

    result = pipeline.run(utterance, method="rules")

    assert result.status == "success"
    assert result.method_requested == "rules-basic"
    assert result.method_used == "rules-basic"
    assert result.validation["status"] == "passed"
    assert "languageMs" in result.timings
    assert result.metadata.get("defaultMethod") == pipeline.default_method_id
    assert isinstance(result.metadata.get("availableMethods"), list)


def test_pipeline_hybrid_fallback_success(pipeline_factory) -> None:
    llm_payloads = {
        "Need a getaway from Amsterdam to Japan": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-2000-1234-aaac-1234567d"],
            "dates": ["2025-11-25"],
        }
    }
    pipeline = pipeline_factory(llm_payloads, popularity_imputer_enabled=False)

    result = pipeline.run("Need a getaway from Amsterdam to Japan", method="hybrid")

    assert result.status == "success"
    assert result.method_requested == "hybrid-v1"
    assert result.method_used == "gemini-2.5-flash"
    assert result.validation["status"] == "passed"
    hybrid_meta = result.metadata.get("hybrid", {})
    assert hybrid_meta.get("methodId") == "hybrid-v1"
    assert hybrid_meta.get("fallbackTriggered") is False
    stages = hybrid_meta.get("stages", [])
    assert stages and stages[0]["id"] == "rules-basic" and stages[0]["status"] == "failed"
    assert stages[-1]["id"] == "gemini-2.5-flash"
    attempts = result.attempts
    assert attempts[0]["method"] == "rules-basic"
    assert attempts[-1]["method"] == "gemini-2.5-flash"



def test_pipeline_records_llm_network_latency(pipeline_factory) -> None:
    llm_payloads = {
        "Measure latency": (
            {
                "airports": ["AMS"],
                "destinations": ["d7b4bb39-2000-1234-aaac-1234567d"],
                "dates": ["2025-11-25"],
            },
            0.05,
        )
    }
    pipeline = pipeline_factory(llm_payloads, popularity_imputer_enabled=False)

    result = pipeline.run("Measure latency", method="llm")

    latency_ms = result.timings.get("llmNetworkMs")
    assert latency_ms is not None
    assert latency_ms >= 40.0
    assert result.method_used == "gemini-2.5-flash"


def test_pipeline_llm_metadata_propagates(pipeline_factory) -> None:
    llm_payloads = {
        "Expose metadata": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-2000-1234-aaac-1234567d"],
            "dates": ["2025-11-25"],
            "metadata": {
                "provider": "stub-llm",
                "promptId": "prompt-123",
                "responseId": "response-456",
            },
        }
    }
    pipeline = pipeline_factory(llm_payloads, popularity_imputer_enabled=False)

    result = pipeline.run("Expose metadata", method="llm")

    llm_meta = result.metadata.get("llm")
    assert isinstance(llm_meta, dict)
    assert llm_meta.get("provider") == "stub-llm"
    assert llm_meta.get("promptId") == "prompt-123"
    assert llm_meta.get("responseId") == "response-456"
    assert result.method_used == "gemini-2.5-flash"


def test_pipeline_prefers_external_llm_when_imputer_disabled(monkeypatch, tmp_path: Path) -> None:
    """Disabling the imputer should not block configured LLM clients."""

    calls: list[str] = []

    class DummyLLMClient:
        def __init__(self, *, settings, fixtures_dir):  # type: ignore[no-untyped-def]
            calls.append("init")

        def __call__(self, text: str) -> Mapping[str, object]:
            calls.append(text)
            return {
                "airports": ["AMS"],
                "destinations": ["d7b4bb39-2000-1234-aaac-1234567d"],
                "dates": ["2025-11-25"],
            }

    monkeypatch.setattr(
        "backend.app.pipeline.pipeline.GeminiStructuredLLMClient", DummyLLMClient
    )

    settings = Settings(
        fixtures_dir=FIXTURES_DIR,
        csv_path=tmp_path / "pipeline-log.csv",
        popularity_imputer_enabled=False,
        llm_api_key="token-123",
        llm_method="llm",
    )

    pipeline = HolidaySearchPipeline(
        settings=settings,
        fixtures_dir=settings.fixtures_dir,
        methods_catalog=settings.load_methods_catalog(),
    )

    result = pipeline.run("Need a getaway from Amsterdam to Japan", method="llm")

    assert calls == ["init", "Need a getaway from Amsterdam to Japan"]
    assert result.method_used == "gemini-2.5-flash"
    assert result.validation["status"] == "passed"


def test_pipeline_hybrid_fallback_failure(pipeline_factory) -> None:
    llm_payloads = {
        "Fallback still missing data": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-2000-1234-aaac-1234567d"],
            "dates": [],
        }
    }
    pipeline = pipeline_factory(llm_payloads, popularity_imputer_enabled=False)

    result = pipeline.run("Fallback still missing data", method="hybrid")

    assert result.status == "failed"
    assert result.method_requested == "hybrid-v1"
    assert result.method_used == "gemini-2.5-flash"
    assert result.validation["status"] == "failed"
    hybrid_meta = result.metadata.get("hybrid", {})
    assert hybrid_meta.get("fallbackTriggered") is True
    stages = hybrid_meta.get("stages", [])
    assert stages and stages[-1].get("fallback") is True
    attempts = result.attempts
    assert len(attempts) == 3
    assert attempts[-1]["status"] == "failed"


def test_dependency_wiring_triggers_llm_when_configured(monkeypatch, tmp_path: Path) -> None:
    """Ensure the pipeline obtained via dependencies honours LLM defaults."""

    from backend.app import dependencies

    for cache in (
        dependencies.get_settings,
        dependencies.get_pipeline,
        dependencies.get_llm_client,
        dependencies.get_methods_catalog,
    ):
        cache.cache_clear()  # type: ignore[attr-defined]

    monkeypatch.setenv("LLM_METHOD", "llm")
    monkeypatch.setenv("LLM_API_KEY", "integration-key")
    monkeypatch.setenv("LLM_API_BASE", "https://mock-llm")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.setenv("CSV_PATH", str(tmp_path / "log.csv"))
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES_DIR))

    calls: list[str] = []

    class DummyLLMClient:
        def __call__(self, text: str) -> Mapping[str, object]:
            calls.append(text)
            return {
                "airports": ["AMS"],
                "destinations": ["d7b4bb39-123d-1234-123f-1234567f"],
                "duration": "2007",
                "flexibility": "3",
                "dates": ["2025-10-10"],
            }

    dummy_client = DummyLLMClient()
    monkeypatch.setattr(
        dependencies,
        "HolidaySearchLLMClient",
        lambda settings, fixtures_dir: dummy_client,
    )

    try:
        pipeline = dependencies.get_pipeline()
        result = pipeline.run("Plan a weekend escape")
    finally:
        dependencies.get_pipeline.cache_clear()  # type: ignore[attr-defined]
        dependencies.get_settings.cache_clear()  # type: ignore[attr-defined]
        dependencies.get_llm_client.cache_clear()  # type: ignore[attr-defined]
        dependencies.get_methods_catalog.cache_clear()  # type: ignore[attr-defined]

    assert result.method_requested == "gemini-2.5-flash"
    assert result.metadata.get("requestedAlias") == "llm"
    assert result.method_used == "gemini-2.5-flash"
    assert calls == ["Plan a weekend escape"]


def test_pipeline_rules_success_with_dutch(pipeline_factory) -> None:
    pipeline = pipeline_factory()
    utterance = (
        "Ik zoek een vakantie vanuit Amsterdam naar Australie op 10 oktober 2025 "
        "voor 7 nachten met +- 3 dagen flexibiliteit."
    )

    result = pipeline.run(utterance, method="rules")

    assert result.status == "success"
    assert result.detection.language == "nl"
    assert result.normalized is not None
    assert result.normalized.language == "nl"
    assert result.method_used == "rules-basic"


def test_pipeline_rules_success_with_french(pipeline_factory) -> None:
    pipeline = pipeline_factory()
    utterance = (
        "Je cherche des vacances au départ de Ostende vers l'Australie le 10 octobre 2025 "
        "pour 7 nuits avec +- 3 jours de flexibilité."
    )

    result = pipeline.run(utterance, method="rules")

    assert result.status == "success"
    assert result.detection.language == "fr"
    assert result.normalized is not None
    assert result.normalized.language == "fr"
    assert result.method_used == "rules-basic"


def test_pipeline_rejects_language_outside_allow_list(pipeline_factory) -> None:
    pipeline = pipeline_factory(allowed_langs=["en"])

    with pytest.raises(ValueError):
        pipeline.run("Je cherche des vacances en Australie", method="rules")


