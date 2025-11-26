from backend.app.services.statistics import (
    AccuracyAssessment,
    Inference,
    P95Assessment,
    clean_response_times,
    evaluate_accuracy,
    evaluate_p95,
)


def test_clean_response_times_filters_outliers_and_invalid_values() -> None:
    raw = [100, None, -5, "oops", 50_000, 320.5, float("nan"), 9999]

    cleaned = clean_response_times(raw, outlier_threshold_ms=10_000)

    assert cleaned == [100.0, 320.5, 9999.0]


def test_evaluate_p95_marks_insufficient_data_when_sample_small() -> None:
    values = [120.0] * 50

    assessment = evaluate_p95(values, threshold_ms=200, min_sample_size=100, alpha=0.05)

    assert isinstance(assessment, P95Assessment)
    assert assessment.inference.inference == "insufficient data"
    assert assessment.inference.p_value is None
    assert assessment.sample_p95_ms == 120.0


def test_evaluate_p95_detects_threshold_regressions() -> None:
    values = [120.0] * 800 + [600.0] * 300

    assessment = evaluate_p95(values, threshold_ms=500, min_sample_size=200, alpha=0.05)

    assert assessment.inference.inference == "above the target"
    assert assessment.sample_p95_ms > 500
    assert assessment.inference.p_value is not None
    assert assessment.inference.confidence is not None
    assert assessment.inference.confidence > 0.95


def test_evaluate_accuracy_flags_drops_below_threshold() -> None:
    successes = 820
    trials = 1000

    assessment = evaluate_accuracy(
        successes=successes,
        trials=trials,
        target=0.9,
        min_sample_size=500,
        alpha=0.05,
    )

    assert isinstance(assessment, AccuracyAssessment)
    assert assessment.inference.inference == "below the target"
    assert assessment.inference.p_value is not None
    assert assessment.inference.confidence is not None


def test_evaluate_accuracy_returns_insufficient_data_when_small_sample() -> None:
    assessment = evaluate_accuracy(
        successes=9,
        trials=10,
        target=0.85,
        min_sample_size=100,
        alpha=0.05,
    )

    assert assessment.inference == Inference(inference="insufficient data", p_value=None, confidence=None)
