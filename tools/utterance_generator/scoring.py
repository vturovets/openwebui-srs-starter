from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Sequence

from .lexicon import LexiconOption

Vector = List[float]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vectors must have the same length")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def average_vectors(vectors: Iterable[Vector]) -> Vector:
    vectors = list(vectors)
    if not vectors:
        raise ValueError("Cannot average zero vectors")
    length = len(vectors[0])
    if any(len(vec) != length for vec in vectors):
        raise ValueError("Vectors must have consistent dimensions")
    sums = [0.0] * length
    for vec in vectors:
        for idx, value in enumerate(vec):
            sums[idx] += value
    return [value / len(vectors) for value in sums]


def build_option_centroid(
    option: LexiconOption, embed_fn: Callable[[str], Vector]
) -> Vector:
    terms = option.terms
    embeddings = [embed_fn(term) for term in terms]
    return average_vectors(embeddings)


@dataclass
class PurityDecision:
    accepted: bool
    top_score: float
    margin: float
    reason: str


@dataclass
class SimilarityBreakdown:
    target_option_id: str
    target_score: float
    top_option_id: str
    top_score: float
    best_non_target_score: float
    target_rank: int | None

    @property
    def margin_to_top(self) -> float:
        return self.target_score - self.top_score

    @property
    def margin_to_best_non_target(self) -> float:
        return self.target_score - self.best_non_target_score


def purity_gate(
    utterance_embedding: Vector,
    target_option_id: str,
    option_centroids: Mapping[str, Vector],
    purity_min_score: float,
    purity_margin: float,
) -> PurityDecision:
    scored = [
        (option_id, cosine_similarity(utterance_embedding, embedding))
        for option_id, embedding in option_centroids.items()
    ]
    scored.sort(key=lambda entry: entry[1], reverse=True)
    top_option, top_score = scored[0]
    runner_up_score = scored[1][1] if len(scored) > 1 else -1.0
    margin = top_score - runner_up_score

    if top_option != target_option_id:
        return PurityDecision(
            accepted=False,
            top_score=top_score,
            margin=margin,
            reason="target_not_top_match",
        )
    if top_score < purity_min_score:
        return PurityDecision(
            accepted=False,
            top_score=top_score,
            margin=margin,
            reason="score_below_threshold",
        )
    if margin < purity_margin:
        return PurityDecision(
            accepted=False,
            top_score=top_score,
            margin=margin,
            reason="insufficient_margin",
        )
    return PurityDecision(
        accepted=True,
        top_score=top_score,
        margin=margin,
        reason="accepted",
    )


def compute_multi_metrics(
    utterance_embedding: Vector,
    target_option_ids: Sequence[str],
    centroids: Mapping[str, Vector],
    coverage_flag: float,
    separation_flag: float,
) -> dict:
    target_scores = {
        option_id: cosine_similarity(utterance_embedding, centroids[option_id])
        for option_id in target_option_ids
        if option_id in centroids
    }
    non_target_scores = [
        cosine_similarity(utterance_embedding, embedding)
        for option_id, embedding in centroids.items()
        if option_id not in target_scores
    ]
    coverage = sum(target_scores.values()) / max(len(target_scores), 1)
    best_target = max(target_scores.values()) if target_scores else 0.0
    best_non_target = max(non_target_scores) if non_target_scores else -1.0
    separation = best_target - best_non_target
    return {
        "coverage": coverage,
        "separation": separation,
        "flag_low_coverage": coverage < coverage_flag,
        "flag_low_separation": separation < separation_flag,
        "scores": target_scores,
    }


def score_option_similarity(
    utterance_embedding: Vector,
    option_centroids: Mapping[str, Vector],
    target_option_id: str,
) -> SimilarityBreakdown:
    scored = [
        (option_id, cosine_similarity(utterance_embedding, embedding))
        for option_id, embedding in option_centroids.items()
    ]
    scored.sort(key=lambda entry: entry[1], reverse=True)

    target_score = next(
        (score for option_id, score in scored if option_id == target_option_id), 0.0
    )
    top_option_id, top_score = scored[0] if scored else ("", 0.0)
    best_non_target_score = next(
        (score for option_id, score in scored if option_id != target_option_id), -1.0
    )
    target_rank = next(
        (index + 1 for index, (option_id, _) in enumerate(scored) if option_id == target_option_id),
        None,
    )

    return SimilarityBreakdown(
        target_option_id=target_option_id,
        target_score=target_score,
        top_option_id=top_option_id,
        top_score=top_score,
        best_non_target_score=best_non_target_score,
        target_rank=target_rank,
    )
