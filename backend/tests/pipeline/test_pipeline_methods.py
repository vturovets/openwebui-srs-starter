from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Mapping

import pytest

from backend.app.config import Settings
from backend.app.integrations.llm import LLMClientHandle, LLMClientRegistry
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
        llm_registry: Mapping[str, LLMClientHandle] | None = None,
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
        settings = Settings(**settings_kwargs)

        catalog = settings.load_methods_catalog()

        if llm_registry is None and responses is not None:
            handles: dict[str, LLMClientHandle] = {}

            def build_stub(method) -> LLMClientHandle:
                method_id = method.id
                provider = str(method.config.get("provider", "openai")) if method.config else "openai"
                model = (
                    str(method.config.get("model"))
                    if method.config and method.config.get("model")
                    else None
                )
                config_payload = dict(method.config) if method.config else {}

                def client(text: str) -> Mapping[str, object]:
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

                return LLMClientHandle(
                    method_id=method_id,
                    provider=provider,
                    client=client,
                    model=model,
                    config=config_payload,
                )

            for method in catalog.list_methods():
                if method.kind != "llm":
                    continue
                handles[method.id] = build_stub(method)

            llm_registry = handles

        pipeline_llm_registry = llm_registry if llm_registry is not None else None

        return HolidaySearchPipeline(
            settings=settings,
            fixtures_dir=settings.fixtures_dir,
            llm_registry=pipeline_llm_registry,
            methods_catalog=settings.load_methods_catalog(),
        )

    return factory


def test_pipeline_rules_only_success(pipeline_factory) -> None:
    pipeline = pipeline_factory()
    utterance = "Book a trip from Amsterdam to Italy on 10 October 2025 for 7 nights"

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
        "Need a getaway from Amsterdam to Spain": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-123c-1234-b123-1234567i"],
            "dates": ["2025-11-25"],
        }
    }
    pipeline = pipeline_factory(llm_payloads)

    result = pipeline.run("Need a getaway from Amsterdam to Spain", method="hybrid")

    assert result.status == "success"
    assert result.method_requested == "hybrid-v1"
    assert result.method_used == "gpt5-default"
    assert result.validation["status"] == "passed"
    hybrid_meta = result.metadata.get("hybrid", {})
    assert hybrid_meta.get("methodId") == "hybrid-v1"
    assert hybrid_meta.get("fallbackTriggered") is False
    stages = hybrid_meta.get("stages", [])
    assert stages and stages[0]["id"] == "rules-basic" and stages[0]["status"] == "failed"
    assert stages[-1]["id"] == "gpt5-default"
    attempts = result.attempts
    assert attempts[0]["method"] == "rules-basic"
    assert attempts[-1]["method"] == "gpt5-default"


def test_pipeline_records_llm_network_latency(pipeline_factory) -> None:
    llm_payloads = {
        "Measure latency": (
            {
                "airports": ["AMS"],
                "destinations": ["d7b4bb39-123c-1234-b123-1234567i"],
                "dates": ["2025-11-25"],
            },
            0.05,
        )
    }
    pipeline = pipeline_factory(llm_payloads)

    result = pipeline.run("Measure latency", method="llm")

    latency_ms = result.timings.get("llmNetworkMs")
    assert latency_ms is not None
    assert latency_ms >= 40.0
    assert result.method_used == "gpt5-default"


def test_pipeline_llm_metadata_propagates(pipeline_factory) -> None:
    llm_payloads = {
        "Expose metadata": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-123c-1234-b123-1234567i"],
            "dates": ["2025-11-25"],
            "metadata": {
                "provider": "stub-llm",
                "promptId": "prompt-123",
                "responseId": "response-456",
            },
        }
    }
    pipeline = pipeline_factory(llm_payloads)

    result = pipeline.run("Expose metadata", method="llm")

    llm_meta = result.metadata.get("llm")
    assert isinstance(llm_meta, dict)
    assert llm_meta.get("provider") == "stub-llm"
    assert llm_meta.get("promptId") == "prompt-123"
    assert llm_meta.get("responseId") == "response-456"
    assert result.method_used == "gpt5-default"


def test_pipeline_selects_llm_provider_clients(pipeline_factory) -> None:
    llm_payloads = {
        "Provider selection": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-123c-1234-b123-1234567i"],
            "dates": ["2025-11-25"],
        }
    }
    pipeline = pipeline_factory(llm_payloads)

    openai_result = pipeline.run("Provider selection", method="llm")
    google_result = pipeline.run("Provider selection", method="gemini-1.5-pro")

    openai_meta = openai_result.metadata.get("llm", {})
    assert openai_meta.get("provider") == "openai"
    assert openai_meta.get("methodId") == "gpt5-default"

    gemini_meta = google_result.metadata.get("llm", {})
    assert gemini_meta.get("provider") == "google"
    assert gemini_meta.get("methodId") == "gemini-1.5-pro"
    config_meta = gemini_meta.get("config", {})
    assert config_meta.get("provider") == "google"
    assert google_result.method_used == "gemini-1.5-pro"


def test_pipeline_catalog_preserves_google_provider(monkeypatch, pipeline_factory) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_BASE", "https://generativelanguage.test/v1beta")

    pipeline = pipeline_factory()

    catalog = pipeline.methods_catalog
    gemini = catalog.methods["gemini-1.5-pro"]

    assert gemini.config["provider"] == "google"
    assert gemini.config["api_base"] == "https://generativelanguage.test/v1beta"
    assert gemini.config["api_key_env"] == "GOOGLE_GENAI_API_KEY"

    gemini_metadata = gemini.to_metadata()
    assert gemini_metadata["provider"] == "google"
    assert gemini_metadata["api_base"] == "https://generativelanguage.test/v1beta"


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
    assert result.method_requested == "hybrid-v1"
    assert result.method_used == "gpt5-default"
    assert result.validation["status"] == "failed"
    hybrid_meta = result.metadata.get("hybrid", {})
    assert hybrid_meta.get("fallbackTriggered") is True
    stages = hybrid_meta.get("stages", [])
    assert stages and stages[-1].get("fallback") is True
    attempts = result.attempts
    assert len(attempts) == 3
    assert attempts[-1]["status"] == "failed"


def test_pipeline_hybrid_triggers_configured_fallback(pipeline_factory, tmp_path: Path) -> None:
    methods_yaml = tmp_path / "methods.yaml"
    methods_yaml.write_text(
        """
defaults:
  timeout_s: 30
  temperature: 0.0

methods:
  - id: rules-basic
    type: rules
    enabled: true
    params:
      dictionary_filename: data/dictionary.csv
      configuration_filename: configs/rules.conf

  - id: gpt5-default
    type: llm
    enabled: true
    provider: openai
    model: gpt-5-chat-latest
    api_base: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    params:
      temperature: 0.1

  - id: fallback-hybrid
    type: hybrid
    enabled: true
    strategy: cascade
    stages:
      - ref: rules-basic
    fallback: gpt5-default
""",
        encoding="utf-8",
    )

    llm_payloads = {
        "Fallback hybrid": {
            "airports": ["AMS"],
            "destinations": ["d7b4bb39-123c-1234-b123-1234567i"],
            "dates": ["2025-11-25"],
        }
    }
    pipeline = pipeline_factory(
        llm_payloads,
        methods_config_path=methods_yaml,
    )

    result = pipeline.run("Fallback hybrid", method="fallback-hybrid")

    assert result.status == "success"
    assert result.method_requested == "fallback-hybrid"
    assert result.method_used == "gpt5-default"
    hybrid_meta = result.metadata.get("hybrid", {})
    assert hybrid_meta.get("fallbackTriggered") is True
    assert hybrid_meta.get("fallback") == "gpt5-default"
    stages = hybrid_meta.get("stages", [])
    assert stages and stages[0]["id"] == "rules-basic"
    assert stages[-1].get("fallback") is True


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
    dummy_handle = LLMClientHandle(
        method_id="gpt5-default",
        provider="openai",
        client=dummy_client,
        model="gpt-test",
    )

    monkeypatch.setattr(
        dependencies.LLMClientRegistry,
        "from_methods_catalog",
        classmethod(
            lambda cls, *, settings, catalog, fixtures_dir: LLMClientRegistry({
                "gpt5-default": dummy_handle
            })
        ),
    )

    try:
        pipeline = dependencies.get_pipeline()
        result = pipeline.run("Plan a weekend escape")
    finally:
        dependencies.get_pipeline.cache_clear()  # type: ignore[attr-defined]
        dependencies.get_settings.cache_clear()  # type: ignore[attr-defined]
        dependencies.get_llm_client.cache_clear()  # type: ignore[attr-defined]
        dependencies.get_methods_catalog.cache_clear()  # type: ignore[attr-defined]

    assert result.method_requested == "gpt5-default"
    assert result.metadata.get("requestedAlias") == "llm"
    assert result.method_used == "gpt5-default"
    assert calls == ["Plan a weekend escape"]
    llm_meta = result.metadata.get("llm", {})
    assert llm_meta.get("provider") == "openai"
    assert llm_meta.get("methodId") == "gpt5-default"


def test_pipeline_rules_success_with_dutch(pipeline_factory) -> None:
    pipeline = pipeline_factory()
    utterance = (
        "Ik zoek een vakantie vanuit Amsterdam naar Spanje op 10 oktober 2025 "
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
        "Je cherche des vacances au départ de Ostende vers l'Italie le 10 octobre 2025 "
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
        pipeline.run("Je cherche des vacances en Italie", method="rules")
