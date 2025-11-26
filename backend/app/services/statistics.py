"""Statistical helpers for import performance assessments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


def _binomial_cdf(successes: int, trials: int, proportion: float) -> float:
    """Compute the lower-tail cumulative probability for a binomial distribution."""

    if trials < 0:
        raise ValueError("Number of trials must be non-negative")
    if successes < 0 or successes > trials:
        raise ValueError("Success count must be within [0, trials]")
    if not 0 <= proportion <= 1:
        raise ValueError("Proportion must be between 0 and 1")

    if trials == 0:
        return 1.0

    # Iterative approach to avoid dealing with large factorials and to reduce
    # the risk of floating point overflow for larger sample sizes.
    failure_prob = 1 - proportion
    prob = failure_prob ** trials
    cumulative = prob

    for i in range(1, successes + 1):
        prob *= (proportion / failure_prob) * (trials - i + 1) / i
        cumulative += prob

    return min(1.0, cumulative)


def _linear_quantile(sorted_values: Sequence[float], percentile: float) -> float:
    """Return the requested quantile using linear interpolation."""

    if not sorted_values:
        raise ValueError("Cannot compute quantile for an empty collection")
    percentile = min(max(percentile, 0.0), 1.0)
    position = percentile * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(len(sorted_values) - 1, lower + 1)
    weight = position - lower

    if upper == lower:
        return sorted_values[lower]
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def clean_response_times(values: Iterable[float | int], outlier_threshold_ms: float) -> list[float]:
    """Remove nulls, non-numerical entries, negative values and outliers."""

    cleaned: list[float] = []
    for value in values:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue

        if not numeric_value >= 0:
            continue
        if not numeric_value <= outlier_threshold_ms:
            continue
        if numeric_value != numeric_value:  # NaN check
            continue
        cleaned.append(numeric_value)

    return cleaned


@dataclass
class Inference:
    inference: str
    p_value: float | None
    confidence: float | None


@dataclass
class P95Assessment:
    sample_p95_ms: float | None
    inference: Inference
    sample_size: int
    successes: int


@dataclass
class AccuracyAssessment:
    accuracy: float
    inference: Inference
    sample_size: int
    successes: int


def evaluate_p95(
    values: Sequence[float],
    threshold_ms: float,
    min_sample_size: int,
    alpha: float,
    percentile: float = 0.95,
) -> P95Assessment:
    """Assess whether the observed P95 meets the target threshold."""

    sample_size = len(values)
    inference = Inference(inference="insufficient data", p_value=None, confidence=None)
    sample_p95 = None

    if sample_size:
        sorted_values = sorted(values)
        sample_p95 = _linear_quantile(sorted_values, percentile)

    successes = sum(1 for value in values if value <= threshold_ms)

    if sample_size < min_sample_size:
        return P95Assessment(
            sample_p95_ms=sample_p95,
            inference=inference,
            sample_size=sample_size,
            successes=successes,
        )

    p_value = _binomial_cdf(successes, sample_size, percentile)
    confidence = 1 - p_value if p_value is not None else None

    outcome = "above the target" if p_value < alpha else "meets the target"

    return P95Assessment(
        sample_p95_ms=sample_p95,
        inference=Inference(inference=outcome, p_value=p_value, confidence=confidence),
        sample_size=sample_size,
        successes=successes,
    )


def evaluate_accuracy(
    successes: int,
    trials: int,
    target: float,
    min_sample_size: int,
    alpha: float,
) -> AccuracyAssessment:
    """Perform a one-sided binomial test for accuracy regression."""

    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("Invalid accuracy sample counts provided")

    accuracy = successes / trials if trials else 0.0
    inference = Inference(inference="insufficient data", p_value=None, confidence=None)

    if trials < min_sample_size:
        return AccuracyAssessment(accuracy=accuracy, inference=inference, sample_size=trials, successes=successes)

    p_value = _binomial_cdf(successes, trials, target)
    confidence = 1 - p_value if p_value is not None else None
    outcome = "below the target" if p_value < alpha else "meets the target"

    return AccuracyAssessment(
        accuracy=accuracy,
        inference=Inference(inference=outcome, p_value=p_value, confidence=confidence),
        sample_size=trials,
        successes=successes,
    )
