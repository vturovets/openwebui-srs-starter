from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.pipeline.configuration import (
    HybridMethodConfig,
    MethodsCatalog,
    load_methods_catalog,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
METHODS_FILE = REPO_ROOT / "config" / "methods.yaml"


def test_methods_catalog_resolves_hybrid_structure() -> None:
    catalog = load_methods_catalog(METHODS_FILE)

    assert isinstance(catalog, MethodsCatalog)
    assert catalog.default_method_id == "rules-basic"
    hybrid = catalog.methods.get("hybrid-v1")
    assert isinstance(hybrid, HybridMethodConfig)
    assert [stage.method.id for stage in hybrid.stages] == ["rules-basic", "gpt5-default"]
    assert hybrid.fallback and hybrid.fallback.id == "gpt5-default"


def test_methods_catalog_expands_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE", "https://example.test/v1")
    catalog = load_methods_catalog(METHODS_FILE)

    llm = catalog.methods["gpt5-default"]
    assert llm.params["temperature"] == 0.1
    assert llm.config["api_base"] == "https://example.test/v1"


def test_methods_catalog_includes_google_gemini(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_BASE", "https://generativelanguage.test/v1beta")
    monkeypatch.setenv("GOOGLE_GENAI_MODEL", "models/gemini-pro-custom")

    catalog = load_methods_catalog(METHODS_FILE)

    gemini = catalog.methods["gemini-1.5-pro"]
    assert gemini.config["provider"] == "google"
    assert gemini.config["api_base"] == "https://generativelanguage.test/v1beta"
    assert gemini.config["model"] == "models/gemini-pro-custom"
    assert gemini.config["api_key_env"] == "GOOGLE_GENAI_API_KEY"
    assert gemini.params["temperature"] == 0.2
    assert gemini.params["top_p"] == 0.95
    assert gemini.params["timeout_s"] == 45

    metadata = gemini.to_metadata()
    assert metadata["provider"] == "google"
    assert metadata["api_key_env"] == "GOOGLE_GENAI_API_KEY"


def test_methods_catalog_honours_explicit_default(tmp_path: Path) -> None:
    methods_yaml = tmp_path / "methods.yaml"
    methods_yaml.write_text(
        """
defaults:
  timeout_s: 30
  temperature: 0.0

default: gpt5-default

methods:
  - id: rules-basic
    type: rules
    enabled: true

  - id: gpt5-default
    type: llm
    enabled: true
""",
        encoding="utf-8",
    )

    catalog = load_methods_catalog(methods_yaml)

    assert catalog.default_method_id == "gpt5-default"


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("rules-basic", "rules-basic"),
        ("rules", "rules-basic"),
        ("LLM", "gpt5-default"),
        (None, "rules-basic"),
    ],
)
def test_methods_catalog_lookup(identifier, expected) -> None:
    catalog = load_methods_catalog(METHODS_FILE)
    alias, method = catalog.resolve(identifier)
    assert method.id == expected
    if identifier:
        assert alias == identifier
    else:
        assert alias is None
