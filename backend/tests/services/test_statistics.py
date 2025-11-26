from __future__ import annotations

from random import Random

from backend.app.statistics import binomial_accuracy_test, bootstrap_p95_delta, filter_response_times


def test_filter_response_times_strips_invalids_and_outliers() -> None:
    values = [100, -5, float("nan"), 0, 9_999, 10_001, "oops"]
    filtered = filter_response_times(values, 10_000)
    assert filtered == [100.0, 0.0, 9_999.0]


def test_bootstrap_p95_reports_meeting_target_when_ci_below_threshold() -> None:
    rng = Random(123)
    values = [500 + rng.randint(-20, 20) for _ in range(1200)]

    result = bootstrap_p95_delta(
        values,
        750,
        alpha=0.05,
        min_sample_size=1000,
        outlier_threshold_ms=10_000,
        resamples=300,
        rng=rng,
    )

    assert result.inference == "meet-target"
    assert result.sample_p95 is not None and result.sample_p95 < 750
    assert result.delta_high is not None and result.delta_high <= 0


def test_bootstrap_p95_reports_above_target_when_ci_clear() -> None:
    rng = Random(321)
    values = [1200 + rng.randint(0, 50) for _ in range(1200)]

    result = bootstrap_p95_delta(
        values,
        1000,
        alpha=0.05,
        min_sample_size=500,
        outlier_threshold_ms=10_000,
        resamples=300,
        rng=rng,
    )

    assert result.inference == "above-target"
    assert result.delta_low is not None and result.delta_low > 0


def test_bootstrap_p95_requires_minimum_sample_size() -> None:
    result = bootstrap_p95_delta([500, 600, 700], 650, min_sample_size=10, rng=Random(1))
    assert result.inference == "insufficient-data"
    assert result.sample_p95 is None


def test_binomial_accuracy_flags_regressions() -> None:
    result = binomial_accuracy_test(successes=50, total=120, threshold=0.85, alpha=0.05, min_sample_size=100)
    assert result.inference == "below-target"
    assert result.p_value is not None and result.p_value < 0.05


def test_binomial_accuracy_meets_target_when_supported_by_sample() -> None:
    result = binomial_accuracy_test(successes=115, total=120, threshold=0.85, alpha=0.05, min_sample_size=100)
    assert result.inference == "meet-target"
    assert result.p_value is not None and result.p_value >= 0.05


def test_binomial_accuracy_honours_min_sample_size() -> None:
    result = binomial_accuracy_test(successes=8, total=10, threshold=0.85, min_sample_size=20)
    assert result.inference == "insufficient-data"
    assert result.p_value is None
