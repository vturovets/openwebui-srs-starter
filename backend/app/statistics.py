from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from random import Random
from typing import Iterable, Sequence

Inference = str


@dataclass
class P95BootstrapResult:
    sample_p95: float | None
    delta_low: float | None
    delta_high: float | None
    inference: Inference
    confidence_level: float
    sample_size: int


@dataclass
class AccuracyTestResult:
    accuracy: float | None
    p_value: float | None
    inference: Inference
    confidence_level: float
    sample_size: int


def filter_response_times(values: Iterable[float], outlier_threshold_ms: float) -> list[float]:
    """Discard null, negative, non-numeric, and outlier response times."""

    cleaned: list[float] = []
    for value in values:
        if not isinstance(value, (int, float)):
            continue
        if not isfinite(value):
            continue
        numeric = float(value)
        if numeric < 0:
            continue
        if numeric > outlier_threshold_ms:
            continue
        cleaned.append(numeric)
    return cleaned


def _quantile(sorted_values: Sequence[float], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("Cannot compute quantile of an empty sequence")

    clamped = min(1.0, max(0.0, percentile))
    position = clamped * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(len(sorted_values) - 1, lower + 1)
    weight = position - lower

    if upper == lower:
        return float(sorted_values[lower])

    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def _bootstrap(values: Sequence[float], resamples: int, rng: Random) -> list[float]:
    n = len(values)
    return [values[rng.randrange(0, n)] for _ in range(resamples)]


def bootstrap_p95_delta(
    values: Iterable[float],
    threshold_ms: float,
    *,
    alpha: float = 0.05,
    min_sample_size: int = 1000,
    outlier_threshold_ms: float = 10_000,
    resamples: int = 500,
    rng: Random | None = None,
) -> P95BootstrapResult:
    """Bootstrap the delta between the observed P95 and the configured threshold."""

    confidence_level = 1 - alpha
    cleaned = filter_response_times(values, outlier_threshold_ms)
    n = len(cleaned)

    if n == 0 or n < min_sample_size:
        return P95BootstrapResult(
            sample_p95=None,
            delta_low=None,
            delta_high=None,
            inference="insufficient-data",
            confidence_level=confidence_level,
            sample_size=n,
        )

    sorted_values = sorted(cleaned)
    sample_p95 = _quantile(sorted_values, 0.95)

    rng = rng or Random()
    deltas: list[float] = []
    for _ in range(resamples):
        resample = _bootstrap(sorted_values, n, rng)
        resample.sort()
        resample_p95 = _quantile(resample, 0.95)
        deltas.append(resample_p95 - threshold_ms)

    deltas.sort()
    lower = _quantile(deltas, alpha / 2)
    upper = _quantile(deltas, 1 - alpha / 2)

    if upper <= 0:
        inference: Inference = "meet-target"
    elif lower > 0:
        inference = "above-target"
    else:
        inference = "insufficient-data"

    return P95BootstrapResult(
        sample_p95=sample_p95,
        delta_low=lower,
        delta_high=upper,
        inference=inference,
        confidence_level=confidence_level,
        sample_size=n,
    )


def _binomial_cdf(k: int, n: int, p: float) -> float:
    if not 0 <= k <= n:
        raise ValueError("k must be between 0 and n inclusive")
    if not 0 <= p <= 1:
        raise ValueError("p must be between 0 and 1")

    if n == 0:
        return 1.0

    if p == 0:
        return 1.0 if k == 0 else 0.0
    if p == 1:
        return 1.0 if k == n else 0.0

    probability = (1 - p) ** n
    cumulative = probability

    for i in range(1, k + 1):
        probability *= ((n - i + 1) / i) * (p / (1 - p))
        cumulative += probability

    return cumulative


def binomial_accuracy_test(
    successes: int,
    total: int,
    threshold: float,
    *,
    alpha: float = 0.05,
    min_sample_size: int = 1000,
) -> AccuracyTestResult:
    """One-sided binomial test for whether accuracy falls below the target threshold."""

    confidence_level = 1 - alpha

    if total <= 0:
        return AccuracyTestResult(
            accuracy=None,
            p_value=None,
            inference="insufficient-data",
            confidence_level=confidence_level,
            sample_size=total,
        )

    accuracy = successes / total

    if total < min_sample_size:
        return AccuracyTestResult(
            accuracy=accuracy,
            p_value=None,
            inference="insufficient-data",
            confidence_level=confidence_level,
            sample_size=total,
        )

    p_value = _binomial_cdf(successes, total, threshold)
    inference: Inference
    if p_value < alpha:
        inference = "below-target"
    else:
        inference = "meet-target"

    return AccuracyTestResult(
        accuracy=accuracy,
        p_value=p_value,
        inference=inference,
        confidence_level=confidence_level,
        sample_size=total,
    )
