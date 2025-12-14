from __future__ import annotations

from collections import Counter
from typing import Dict, List

import pytest

from tools.utterance_generator.combinations import generate_combinations
from tools.utterance_generator.lexicon import LexiconOption
from tools.utterance_generator.scoring import (
    build_option_centroid,
    compute_multi_metrics,
    cosine_similarity,
    purity_gate,
)


def test_lexicon_option_validation_and_terms() -> None:
    payload = {
        "filterId": "F1",
        "filterName": "Filter",
        "optionId": "O1",
        "optionName": "Option",
        "synonyms": ["alpha", " beta "],
    }
    option = LexiconOption.from_dict(payload)
    assert option.optionName == "Option"
    assert option.synonyms == ["alpha", "beta"]
    assert option.terms == ["Option", "alpha", "beta"]

    with pytest.raises(ValueError):
        LexiconOption.from_dict({"filterId": "", "filterName": "F", "optionId": "O", "optionName": ""})


def test_generate_combinations_respects_filter_uniqueness() -> None:
    options = [
        LexiconOption("F1", "Filter1", "O1", "One", []),
        LexiconOption("F2", "Filter2", "O2", "Two", []),
        LexiconOption("F3", "Filter3", "O3", "Three", []),
        LexiconOption("F4", "Filter4", "O4", "Four", []),
    ]
    combos = generate_combinations(options, total=6, seed=1)
    assert len(combos) == 6
    assert all(len(combo.options) >= 2 for combo in combos)
    assert all(len(set(combo.filter_ids)) == len(combo.options) for combo in combos)
    size_counts = Counter(len(combo.options) for combo in combos)
    assert sum(size_counts.values()) == 6
    assert all(size in (2, 3, 4) for size in size_counts)


def test_build_option_centroid_includes_option_name() -> None:
    option = LexiconOption("F1", "Filter", "O1", "Option", ["alias", "alt"])
    embeddings: Dict[str, List[float]] = {
        "Option": [1.0, 0.0],
        "alias": [0.0, 1.0],
        "alt": [0.5, 0.5],
    }

    centroid = build_option_centroid(option, embed_fn=lambda text: embeddings[text])
    assert centroid == [pytest.approx(0.5), pytest.approx(0.5)]


def test_purity_gate_accepts_only_with_margin_and_threshold() -> None:
    centroids = {
        "O1": [1.0, 0.0],
        "O2": [0.0, 1.0],
    }
    utterance = [0.9, 0.0]
    accepted = purity_gate(utterance, "O1", centroids, purity_min_score=0.5, purity_margin=0.05)
    assert accepted.accepted
    assert accepted.reason == "accepted"

    rejected = purity_gate(utterance, "O2", centroids, purity_min_score=0.5, purity_margin=0.2)
    assert not rejected.accepted
    assert rejected.reason in {"target_not_top_match", "insufficient_margin"}


def test_compute_multi_metrics_flags_coverage_and_separation() -> None:
    centroids = {
        "O1": [1.0, 0.0],
        "O2": [0.0, 1.0],
        "O3": [0.5, 0.5],
    }
    utterance = [0.7, 0.7]
    metrics = compute_multi_metrics(
        utterance_embedding=utterance,
        target_option_ids=["O1", "O2"],
        centroids=centroids,
        coverage_flag=0.8,
        separation_flag=0.05,
    )
    assert pytest.approx(metrics["coverage"], rel=1e-3) == (
        cosine_similarity(utterance, centroids["O1"]) + cosine_similarity(utterance, centroids["O2"])
    ) / 2
    assert metrics["flag_low_coverage"] is True
    assert metrics["flag_low_separation"] is True
