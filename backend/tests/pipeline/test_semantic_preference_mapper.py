from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app.fixtures.filter_catalogue import FiltersCatalogue
from backend.app.pipeline import preferences_mapping
from backend.app.pipeline.preferences_mapping import SemanticPreferenceMapper


def build_catalogue(tmp_path: Path, rows: list[str]) -> FiltersCatalogue:
    csv_path = tmp_path / "filters.csv"
    csv_path.write_text(
        "filterId,filterLabel,optionId,optionLabel,synonyms\n" + "\n".join(rows),
        encoding="utf-8",
    )
    return FiltersCatalogue(csv_path)


def install_dummy_model(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, np.ndarray],
    *,
    default_vector: np.ndarray,
) -> dict[str, object]:
    holder: dict[str, object] = {}

    class DummySentenceTransformer:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name
            self.calls: list[str] = []
            holder["instance"] = self

        def encode(self, text: str) -> np.ndarray:
            self.calls.append(text)
            vector = mapping.get(text)
            if vector is None:
                vector = default_vector
            return np.array(vector, dtype=float)

    monkeypatch.setattr(
        preferences_mapping, "SentenceTransformer", DummySentenceTransformer
    )
    return holder


def test_semantic_mapper_raises_on_model_load_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def raise_error(_: str) -> None:
        raise OSError("model load failed")

    monkeypatch.setattr(preferences_mapping, "SentenceTransformer", raise_error)
    catalogue = build_catalogue(
        tmp_path,
        [
            "facilities,Facilities,wifi,Wi-Fi,wifi",
        ],
    )

    with pytest.raises(RuntimeError, match="Failed to load sentence-transformer model"):
        SemanticPreferenceMapper(catalogue)


def test_semantic_mapper_precomputes_embeddings_and_cache_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalogue = build_catalogue(
        tmp_path,
        [
            "facilities,Facilities,wifi,Wi-Fi,wifi",
            "facilities,Facilities,pool,Pool,pool",
            "board,Board,all,All Inclusive,all inclusive",
        ],
    )
    default_vector = np.array([1.0, 2.0, 3.0])
    holder = install_dummy_model(
        monkeypatch,
        {},
        default_vector=default_vector,
    )

    mapper = SemanticPreferenceMapper(catalogue, similarity_threshold=0.1)
    model = holder["instance"]

    assert len(mapper._option_vectors) == 3
    assert len(model.calls) == 3
    for vector in mapper._option_vectors.values():
        assert vector.shape == (3,)
        assert np.isclose(np.linalg.norm(vector), 1.0)


def test_semantic_mapper_similarity_orders_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalogue = build_catalogue(
        tmp_path,
        [
            "facilities,Facilities,wifi,Wi-Fi,wifi",
            "facilities,Facilities,pool,Pool,pool",
            "facilities,Facilities,spa,Spa,spa",
        ],
    )
    mapping = {
        "Facilities: Wi-Fi": np.array([1.0, 0.0]),
        "Facilities: Pool": np.array([0.9, 0.1]),
        "Facilities: Spa": np.array([0.0, 1.0]),
        "need wifi": np.array([1.0, 0.0]),
    }
    holder = install_dummy_model(
        monkeypatch, mapping, default_vector=np.array([0.0, 0.0])
    )

    mapper = SemanticPreferenceMapper(catalogue, similarity_threshold=0.1)
    status, selections, _ = mapper.map("need wifi", language="en")

    assert status == "success"
    assert holder["instance"] is not None
    assert selections[0].options[0].id == "wifi"
    assert selections[0].options[1].id == "pool"


def test_semantic_mapper_applies_threshold_and_top_k_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalogue = build_catalogue(
        tmp_path,
        [
            "facilities,Facilities,wifi,Wi-Fi,wifi",
            "facilities,Facilities,pool,Pool,pool",
            "facilities,Facilities,spa,Spa,spa",
        ],
    )
    mapping = {
        "Facilities: Wi-Fi": np.array([0.6, 0.8]),
        "Facilities: Pool": np.array([0.5, 0.5]),
        "Facilities: Spa": np.array([0.4, 0.2]),
        "want spa": np.array([0.0, 1.0]),
    }
    install_dummy_model(monkeypatch, mapping, default_vector=np.array([0.0, 0.0]))

    mapper = SemanticPreferenceMapper(
        catalogue, similarity_threshold=0.99, top_k=2
    )
    status, selections, _ = mapper.map("want spa", language="en")

    assert status == "success"
    assert len(selections[0].options) == 2
    assert all(not option.selected for option in selections[0].options)


def test_semantic_mapper_negation_reduces_confidence_and_unselects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalogue = build_catalogue(
        tmp_path,
        [
            "facilities,Facilities,wifi,Wi-Fi,wifi",
            "facilities,Facilities,pool,Pool,pool",
        ],
    )
    mapping = {
        "Facilities: Wi-Fi": np.array([1.0, 0.0]),
        "Facilities: Pool": np.array([0.0, 1.0]),
        "wifi": np.array([1.0, 0.0]),
    }
    install_dummy_model(monkeypatch, mapping, default_vector=np.array([0.0, 0.0]))

    mapper = SemanticPreferenceMapper(
        catalogue, similarity_threshold=0.2, negation_penalty=0.25
    )
    status, selections, mappings = mapper.map("no wifi", language="en")

    assert status == "success"
    wifi_option = selections[0].options[0]
    assert wifi_option.id == "wifi"
    assert wifi_option.selected is False
    assert wifi_option.confidence is not None
    assert wifi_option.confidence < 1.0
    assert mappings[0]["blocked"] is True
