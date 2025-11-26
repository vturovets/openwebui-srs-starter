from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..config import Settings


def _to_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _normalise_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _logaddexp(a: float, b: float) -> float:
    if math.isinf(a) and a < 0:
        return b
    if math.isinf(b) and b < 0:
        return a
    if a > b:
        return a + math.log1p(math.exp(b - a))
    return b + math.log1p(math.exp(a - b))


def _identify_usage_metric(key: str) -> str | None:
    if "token" in key:
        if any(marker in key for marker in ("out", "output", "completion", "response", "candidate")):
            return "tokensOut"
        if any(marker in key for marker in ("in", "input", "prompt")):
            return "tokensIn"
    if "api" in key and ("call" in key or "request" in key or key.endswith("requestcount")):
        return "apiCalls"
    if key == "requests":
        return "apiCalls"
    if "cpu" in key and any(marker in key for marker in ("ms", "millisecond", "time", "duration")):
        return "cpuMs"
    ram_indicator = "ram" in key or "memory" in key or "mem" in key
    size_indicator = "mb" in key or "megabyte" in key or "byte" in key
    duration_indicator = "sec" in key or "time" in key or "duration" in key
    if ram_indicator and (size_indicator or "footprint" in key) and (duration_indicator or "footprint" in key):
        return "ramMbSeconds"
    return None


def _should_descend(key: str) -> bool:
    return any(
        marker in key
        for marker in (
            "usage",
            "metric",
            "footprint",
            "resource",
            "component",
            "summary",
            "total",
            "aggregate",
        )
    )


class UsageAccumulator:
    def __init__(self) -> None:
        self._totals: dict[str, float] = {
            "tokensIn": 0.0,
            "tokensOut": 0.0,
            "apiCalls": 0.0,
            "cpuMs": 0.0,
            "ramMbSeconds": 0.0,
        }
        self._seen: set[str] = set()

    def _record_usage_value(self, metric: str, value: object) -> bool:
        numeric_value = _to_number(value)
        if numeric_value is None:
            return False
        self._totals[metric] += numeric_value
        self._seen.add(metric)
        return True

    def _process_usage_object(
        self, record: Mapping[str, object], *, visited: set[int], allow_nested: bool
    ) -> bool:
        record_id = id(record)
        if record_id in visited:
            return False
        visited.add(record_id)

        updated = False
        for key, raw_value in record.items():
            normalised_key = _normalise_key(str(key))
            metric = _identify_usage_metric(normalised_key)
            if metric and self._record_usage_value(metric, raw_value):
                updated = True
                continue

            if not allow_nested:
                continue

            if isinstance(raw_value, list):
                for item in raw_value:
                    if isinstance(item, Mapping) and self._process_usage_object(
                        item, visited=visited, allow_nested=True
                    ):
                        updated = True
                continue

            if isinstance(raw_value, Mapping) and _should_descend(normalised_key):
                if self._process_usage_object(raw_value, visited=visited, allow_nested=True):
                    updated = True

        return updated

    def _process_usage_array(self, entries: Sequence[object], *, visited: set[int]) -> bool:
        updated = False
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            record_id = id(entry)
            if record_id in visited:
                continue
            visited.add(record_id)

            component_updated = False
            usage = entry.get("usage") if isinstance(entry, Mapping) else None
            if isinstance(usage, Mapping) and self._process_usage_object(
                usage, visited=visited, allow_nested=True
            ):
                component_updated = True

            metrics = entry.get("metrics") if isinstance(entry, Mapping) else None
            if isinstance(metrics, Mapping) and self._process_usage_object(
                metrics, visited=visited, allow_nested=True
            ):
                component_updated = True

            if not component_updated and self._process_usage_object(
                entry, visited=visited, allow_nested=False
            ):
                component_updated = True

            if component_updated:
                updated = True

        return updated

    def consume(self, metadata: Mapping[str, object] | None) -> None:
        if not isinstance(metadata, Mapping):
            return

        visited: set[int] = set()
        components: list[Sequence[object]] = []

        if isinstance(metadata.get("components"), Sequence):
            components.append(metadata.get("components"))

        usage = metadata.get("usage") if isinstance(metadata, Mapping) else None
        if isinstance(usage, Mapping):
            components_list = usage.get("components") if isinstance(usage.get("components"), Sequence) else None
            if isinstance(components_list, Sequence):
                components.append(components_list)

        usage_metadata = metadata.get("usageMetadata") if isinstance(metadata.get("usageMetadata"), Mapping) else None

        llm = metadata.get("llm") if isinstance(metadata.get("llm"), Mapping) else None
        llm_usage_metadata = None
        if isinstance(llm, Mapping):
            llm_components = llm.get("components") if isinstance(llm.get("components"), Sequence) else None
            if isinstance(llm_components, Sequence):
                components.append(llm_components)
            llm_usage = llm.get("usage") if isinstance(llm.get("usage"), Mapping) else None
            if isinstance(llm_usage, Mapping):
                llm_usage_components = llm_usage.get("components")
                if isinstance(llm_usage_components, Sequence):
                    components.append(llm_usage_components)
            if usage_metadata is None and isinstance(llm.get("usageMetadata"), Mapping):
                llm_usage_metadata = llm.get("usageMetadata")

        usage_footprint = metadata.get("usageFootprint") if isinstance(metadata.get("usageFootprint"), Mapping) else None
        metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), Mapping) else None
        pipeline = metadata.get("pipeline") if isinstance(metadata.get("pipeline"), Mapping) else None
        resources = metadata.get("resources") if isinstance(metadata.get("resources"), Mapping) else None
        details = metadata.get("details") if isinstance(metadata.get("details"), Mapping) else None

        for container in (usage_footprint, metrics, pipeline, resources, details):
            if isinstance(container, Mapping):
                components_array = container.get("components")
                if isinstance(components_array, Sequence):
                    components.append(components_array)

        for array in components:
            if isinstance(array, Sequence) and self._process_usage_array(array, visited=visited):
                continue

        containers = [
            usage,
            usage_metadata,
            llm_usage_metadata,
            usage_footprint,
            metrics,
            llm.get("usage") if isinstance(llm, Mapping) else None,
            resources,
        ]
        for container in containers:
            if isinstance(container, Mapping):
                self._process_usage_object(container, visited=visited, allow_nested=True)

    def summary(self) -> dict[str, float]:
        return {
            key: round(value, 6)
            for key, value in self._totals.items()
            if key in self._seen
        }


def _has_expected_value_mismatches(metadata: Mapping[str, object] | None) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    mismatches = metadata.get("expectedValueMismatches")
    if not isinstance(mismatches, Sequence):
        return False
    return len(mismatches) > 0


def _extract_total_ms(metadata: Mapping[str, object] | None) -> float | None:
    if not isinstance(metadata, Mapping):
        return None
    timings = metadata.get("timings")
    if not isinstance(timings, Mapping):
        return None
    candidate_keys = ("totalMs", "pipelineTotalMs", "total", "totalMilliseconds")
    for key in candidate_keys:
        value = _to_number(timings.get(key))
        if value is not None:
            return value
    for key, raw_value in timings.items():
        if "total" not in str(key).lower():
            continue
        value = _to_number(raw_value)
        if value is not None:
            return value
    return None


def _calculate_percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("Cannot calculate percentile of empty sequence")
    if len(values) == 1:
        return float(values[0])
    sorted_values = sorted(values)
    position = percentile * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    fraction = position - lower
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return lower_value + (upper_value - lower_value) * fraction


def _bootstrap_delta_ci(
    values: Sequence[float],
    *,
    threshold: float,
    alpha: float,
    iterations: int = 2000,
    seed: int = 1337,
) -> tuple[float, float]:
    if not values:
        raise ValueError("Cannot bootstrap confidence interval for empty values")
    rng = random.Random(seed)
    deltas: list[float] = []
    n = len(values)
    for _ in range(iterations):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        sample_p95 = _calculate_percentile(sample, 0.95)
        deltas.append(sample_p95 - threshold)
    deltas.sort()
    lower_index = int((alpha / 2) * (iterations - 1))
    upper_index = int((1 - alpha / 2) * (iterations - 1))
    return deltas[lower_index], deltas[upper_index]


def _binomial_cdf(k: int, n: int, p: float) -> float:
    if n <= 0:
        return float("nan")
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    log_probs: list[float] = []
    for i in range(0, k + 1):
        log_prob = (
            math.lgamma(n + 1)
            - math.lgamma(i + 1)
            - math.lgamma(n - i + 1)
            + i * math.log(p)
            + (n - i) * math.log(1 - p)
        )
        log_probs.append(log_prob)
    total_log_prob = log_probs[0]
    for log_prob in log_probs[1:]:
        total_log_prob = _logaddexp(total_log_prob, log_prob)
    return math.exp(total_log_prob)


@dataclass(slots=True)
class P95Assessment:
    value_ms: float | None
    ci_low_ms: float | None
    ci_high_ms: float | None
    threshold_ms: float
    inference: str
    confidence_level: float
    sample_size: int
    considered_count: int


@dataclass(slots=True)
class AccuracyAssessment:
    value: float | None
    threshold: float
    p_value: float | None
    inference: str
    confidence_level: float
    sample_size: int
    success_count: int


@dataclass(slots=True)
class PerformanceSummary:
    method: str | None
    request_count: int
    mean_response_ms: float | None
    p95: P95Assessment
    accuracy: AccuracyAssessment


@dataclass(slots=True)
class ImportSummaryResult:
    performance: PerformanceSummary
    usage: dict[str, float]


class ImportSummaryReporter:
    def __init__(self, settings: Settings, *, bootstrap_iterations: int = 2000) -> None:
        self._settings = settings
        self._bootstrap_iterations = bootstrap_iterations
        self._bootstrap_seed = 1337

    def summarise(
        self,
        *,
        method: str | None,
        operations: Sequence[Mapping[str, Any]],
    ) -> ImportSummaryResult:
        request_count = len(operations)
        mismatch_count = 0
        latencies: list[float] = []
        usage_accumulator = UsageAccumulator()

        for operation in operations:
            metadata = operation.get("metadata") if isinstance(operation, Mapping) else None
            if _has_expected_value_mismatches(metadata):
                mismatch_count += 1
            total_ms = _extract_total_ms(metadata)
            if total_ms is not None and total_ms >= 0 and total_ms <= self._settings.p95_outliers_threshold:
                latencies.append(total_ms)
            usage_accumulator.consume(metadata)

        mean_response_ms = None
        if latencies:
            mean_response_ms = sum(latencies) / len(latencies)

        confidence_level = 1 - self._settings.alpha
        min_sample_size = max(0, int(self._settings.min_sample_size))

        p95_value = _calculate_percentile(latencies, 0.95) if latencies else None
        p95_ci_low: float | None = None
        p95_ci_high: float | None = None
        p95_inference = "insufficient-data"
        if p95_value is not None and request_count >= min_sample_size:
            delta_low, delta_high = _bootstrap_delta_ci(
                latencies,
                threshold=self._settings.import_p95_threshold_ms,
                alpha=self._settings.alpha,
                iterations=self._bootstrap_iterations,
                seed=self._bootstrap_seed,
            )
            p95_ci_low = delta_low
            p95_ci_high = delta_high
            if delta_high <= 0:
                p95_inference = "meet-target"
            elif delta_low > 0:
                p95_inference = "above-target"
            else:
                p95_inference = "insufficient-data"

        p95_assessment = P95Assessment(
            value_ms=p95_value,
            ci_low_ms=p95_ci_low,
            ci_high_ms=p95_ci_high,
            threshold_ms=float(self._settings.import_p95_threshold_ms),
            inference=p95_inference,
            confidence_level=confidence_level,
            sample_size=request_count,
            considered_count=len(latencies),
        )

        success_count = max(0, request_count - mismatch_count)
        accuracy_value = success_count / request_count if request_count else None
        accuracy_inference = "insufficient-data"
        p_value: float | None = None
        if accuracy_value is not None and request_count >= min_sample_size:
            p_value = _binomial_cdf(success_count, request_count, self._settings.import_accuracy_threshold)
            accuracy_inference = "below-target" if p_value < self._settings.alpha else "meet-target"

        accuracy_assessment = AccuracyAssessment(
            value=accuracy_value,
            threshold=self._settings.import_accuracy_threshold,
            p_value=p_value,
            inference=accuracy_inference,
            confidence_level=confidence_level,
            sample_size=request_count,
            success_count=success_count,
        )

        performance = PerformanceSummary(
            method=method,
            request_count=request_count,
            mean_response_ms=mean_response_ms,
            p95=p95_assessment,
            accuracy=accuracy_assessment,
        )

        usage_summary = usage_accumulator.summary()
        return ImportSummaryResult(performance=performance, usage=usage_summary)


__all__ = [
    "AccuracyAssessment",
    "ImportSummaryResult",
    "ImportSummaryReporter",
    "P95Assessment",
    "PerformanceSummary",
]
