from pathlib import Path

import numpy as np
import pytest

from backend.app.config import Settings
from backend.app.pipeline import preferences_mapping
from backend.app.pipeline.preferences import PreferencesPipeline


REPO_ROOT = Path(__file__).resolve().parents[3]


def build_pipeline() -> PreferencesPipeline:
    settings = Settings(
        fixtures_dir=REPO_ROOT / "fixtures",
        filters_options_path=REPO_ROOT / "fixtures" / "filters_options_rules_test.csv",
    )
    return PreferencesPipeline(settings=settings)


def test_preferences_pipeline_emits_catalogue_filters() -> None:
    pipeline = build_pipeline()

    result = pipeline.run("Need wifi and scuba", method="rules-basic")

    assert result.status == "success"
    filter_ids = {entry["filterId"] for entry in result.filters}
    assert "facilities" in filter_ids
    facilities = next(entry for entry in result.filters if entry["filterId"] == "facilities")
    option_ids = {option["optionId"] for option in facilities["options"]}
    assert {"wifi", "scuba"}.issubset(option_ids)

    assert result.metadata["method"] == "rules-basic"
    assert result.timings["totalMs"] >= result.timings["languageMs"]


def test_preferences_pipeline_no_match_returns_empty_filters() -> None:
    pipeline = build_pipeline()

    result = pipeline.run("This text should not match", method="rules-basic")

    assert result.status == "no-preferences-detected"
    assert result.filters == []


def test_preferences_pipeline_records_requested_alias() -> None:
    pipeline = build_pipeline()

    result = pipeline.run("Need wifi and scuba", method="rules")

    assert result.status == "success"
    assert result.method_used == "rules-basic"
    assert result.method_requested == "rules"


def test_preferences_pipeline_semantic_method_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = {
        "Facilities: Wi-Fi": np.array([1.0, 0.0]),
        "need wifi": np.array([1.0, 0.0]),
    }

    class DummySentenceTransformer:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def encode(self, text: str) -> np.ndarray:
            vector = mapping.get(text)
            if vector is None:
                vector = np.array([0.0, 0.0])
            return np.array(vector, dtype=float)

    monkeypatch.setattr(
        preferences_mapping, "SentenceTransformer", DummySentenceTransformer
    )

    pipeline = build_pipeline()

    result = pipeline.run("need wifi", method="semantic-basic")

    assert result.status == "success"
    assert result.method_used == "semantic-basic"
    filter_ids = {entry["filterId"] for entry in result.filters}
    assert "facilities" in filter_ids
    facilities = next(entry for entry in result.filters if entry["filterId"] == "facilities")
    option_ids = {option["optionId"] for option in facilities["options"]}
    assert "wifi" in option_ids
