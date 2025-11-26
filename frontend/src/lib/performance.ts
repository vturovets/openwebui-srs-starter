export type PerformanceInference = 'meet-target' | 'above-target' | 'below-target' | 'insufficient-data';

export type ThresholdAssessment = {
  sampleP95: number | null;
  deltaLow: number | null;
  deltaHigh: number | null;
  inference: PerformanceInference;
  confidenceLevel: number;
  sampleSize: number;
};

export type AccuracyAssessment = {
  accuracy: number | null;
  pValue: number | null;
  inference: PerformanceInference;
  confidenceLevel: number;
  sampleSize: number;
};

function cloneAndSort(values: number[]): number[] {
  return [...values].sort((a, b) => a - b);
}

export function filterResponseTimes(values: number[], outlierThresholdMs: number): number[] {
  return values.filter((value) => Number.isFinite(value) && value >= 0 && value <= outlierThresholdMs);
}

function getQuantile(sorted: number[], percentile: number): number {
  if (sorted.length === 0) {
    throw new Error('Cannot compute quantile for empty set');
  }

  const clampedPercentile = Math.min(1, Math.max(0, percentile));
  const index = clampedPercentile * (sorted.length - 1);
  const lowerIndex = Math.floor(index);
  const upperIndex = Math.min(sorted.length - 1, lowerIndex + 1);
  const weight = index - lowerIndex;

  if (upperIndex === lowerIndex) {
    return sorted[lowerIndex];
  }

  return sorted[lowerIndex] * (1 - weight) + sorted[upperIndex] * weight;
}

export function calculatePercentile(values: number[], percentile: number): number {
  if (!values.length) {
    throw new Error('Cannot compute percentile for empty array');
  }
  return getQuantile(cloneAndSort(values), percentile);
}

function sampleWithReplacement(values: number[], count: number, randomFn: () => number): number[] {
  const sampled: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const index = Math.floor(randomFn() * values.length);
    sampled.push(values[index]);
  }
  return sampled;
}

export function bootstrapP95Delta({
  values,
  thresholdMs,
  alpha,
  minSampleSize,
  outlierThresholdMs,
  resamples = 500,
  randomFn = Math.random,
}: {
  values: number[];
  thresholdMs: number;
  alpha: number;
  minSampleSize: number;
  outlierThresholdMs: number;
  resamples?: number;
  randomFn?: () => number;
}): ThresholdAssessment {
  const confidenceLevel = 1 - alpha;
  const cleaned = filterResponseTimes(values, outlierThresholdMs);
  const sampleSize = cleaned.length;

  if (sampleSize === 0 || sampleSize < minSampleSize) {
    return {
      sampleP95: null,
      deltaLow: null,
      deltaHigh: null,
      inference: 'insufficient-data',
      confidenceLevel,
      sampleSize,
    };
  }

  const sorted = cloneAndSort(cleaned);
  const sampleP95 = getQuantile(sorted, 0.95);

  const deltas: number[] = [];
  for (let i = 0; i < resamples; i += 1) {
    const resample = sampleWithReplacement(sorted, sampleSize, randomFn).sort((a, b) => a - b);
    const resampleP95 = getQuantile(resample, 0.95);
    deltas.push(resampleP95 - thresholdMs);
  }

  deltas.sort((a, b) => a - b);
  const deltaLow = getQuantile(deltas, alpha / 2);
  const deltaHigh = getQuantile(deltas, 1 - alpha / 2);

  let inference: PerformanceInference;
  if (deltaHigh <= 0) {
    inference = 'meet-target';
  } else if (deltaLow > 0) {
    inference = 'above-target';
  } else {
    inference = 'insufficient-data';
  }

  return { sampleP95, deltaLow, deltaHigh, inference, confidenceLevel, sampleSize };
}

function binomialCdf(k: number, n: number, p: number): number {
  if (k < 0 || k > n) {
    throw new Error('k must be between 0 and n inclusive');
  }
  if (p < 0 || p > 1) {
    throw new Error('p must be between 0 and 1');
  }

  if (n === 0) {
    return 1;
  }
  if (p === 0) {
    return k === 0 ? 1 : 0;
  }
  if (p === 1) {
    return k === n ? 1 : 0;
  }

  let probability = (1 - p) ** n;
  let cumulative = probability;

  for (let i = 1; i <= k; i += 1) {
    probability *= ((n - i + 1) / i) * (p / (1 - p));
    cumulative += probability;
  }

  return cumulative;
}

export function binomialAccuracyTest({
  successes,
  total,
  threshold,
  alpha,
  minSampleSize,
}: {
  successes: number;
  total: number;
  threshold: number;
  alpha: number;
  minSampleSize: number;
}): AccuracyAssessment {
  const confidenceLevel = 1 - alpha;

  if (total <= 0) {
    return { accuracy: null, pValue: null, inference: 'insufficient-data', confidenceLevel, sampleSize: total };
  }

  const accuracy = successes / total;

  if (total < minSampleSize) {
    return { accuracy, pValue: null, inference: 'insufficient-data', confidenceLevel, sampleSize: total };
  }

  const pValue = binomialCdf(successes, total, threshold);
  const inference: PerformanceInference = pValue < alpha ? 'below-target' : 'meet-target';

  return { accuracy, pValue, inference, confidenceLevel, sampleSize: total };
}
