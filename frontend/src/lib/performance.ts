export type PerformanceInference = 'meets-target' | 'violates-target' | 'inconclusive';

export type ThresholdAssessment = {
  sampleP95: number;
  standardErrorMs: number | null;
  thresholdMs: number;
  thresholdBreached: boolean;
  significantBreach: boolean | null;
  zScore: number | null;
  inference: PerformanceInference;
};

function cloneAndSort(values: number[]): number[] {
  return [...values].sort((a, b) => a - b);
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

function estimateQuantileDerivative(sorted: number[], percentile: number): number | null {
  const n = sorted.length;
  if (n < 2) {
    return null;
  }

  const delta = Math.min(0.5, Math.max(1 / n, 0.5 / Math.sqrt(n)));
  const lowerP = Math.max(0, percentile - delta);
  const upperP = Math.min(1, percentile + delta);
  const probabilitySpan = upperP - lowerP;

  if (probabilitySpan <= 0) {
    return null;
  }

  const lowerQuantile = getQuantile(sorted, lowerP);
  const upperQuantile = getQuantile(sorted, upperP);

  if (upperQuantile === lowerQuantile) {
    return 0;
  }

  return (upperQuantile - lowerQuantile) / probabilitySpan;
}

function clampAlpha(alpha: number): number {
  if (!Number.isFinite(alpha)) {
    return 0.05;
  }
  const clamped = Math.min(Math.max(alpha, 1e-6), 0.5);
  return clamped;
}

function normalQuantile(p: number): number {
  // Acklam's approximation for the inverse normal CDF
  const a = [
    -3.969683028665376e1,
    2.209460984245205e2,
    -2.759285104469687e2,
    1.38357751867269e2,
    -3.066479806614716e1,
    2.506628277459239e0,
  ];
  const b = [
    -5.447609879822406e1,
    1.615858368580409e2,
    -1.556989798598866e2,
    6.680131188771972e1,
    -1.328068155288572e1,
  ];
  const c = [
    -7.784894002430293e-3,
    -3.223964580411365e-1,
    -2.400758277161838e0,
    -2.549732539343734e0,
    4.374664141464968e0,
    2.938163982698783e0,
  ];
  const d = [
    7.784695709041462e-3,
    3.224671290700398e-1,
    2.445134137142996e0,
    3.754408661907416e0,
  ];

  if (p <= 0) {
    return -Infinity;
  }
  if (p >= 1) {
    return Infinity;
  }

  const plow = 0.02425;
  const phigh = 1 - plow;

  let q: number;
  let r: number;

  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p));
    return (
      (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    );
  }

  if (phigh < p) {
    q = Math.sqrt(-2 * Math.log(1 - p));
    return -(
      (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    );
  }

  q = p - 0.5;
  r = q * q;

  return (
    (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
    (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
  );
}

export function assessP95Threshold({
  values,
  requestCount,
  thresholdMs,
  sampleSize,
  alpha,
  percentile = 0.95,
}: {
  values: number[];
  requestCount: number;
  thresholdMs: number;
  sampleSize: number;
  alpha: number;
  percentile?: number;
}): ThresholdAssessment | null {
  const validValues = values.filter((value) => Number.isFinite(value));
  const n = validValues.length;

  if (!n) {
    return null;
  }

  const minimumSample = Math.max(0, Math.floor(sampleSize));
  if (minimumSample > 0 && requestCount < minimumSample) {
    return null;
  }

  const sorted = cloneAndSort(validValues);
  const sampleP95 = getQuantile(sorted, percentile);
  const derivative = estimateQuantileDerivative(sorted, percentile);

  let standardErrorMs: number | null = null;
  if (derivative !== null) {
    const variance = (percentile * (1 - percentile)) / n * derivative * derivative;
    standardErrorMs = variance >= 0 ? Math.sqrt(variance) : null;
  }

  const thresholdBreached = sampleP95 > thresholdMs;
  const alphaClamped = clampAlpha(alpha);
  const criticalZ = normalQuantile(1 - alphaClamped);

  let zScore: number | null = null;
  let significantBreach: boolean | null = null;

  if (standardErrorMs === 0) {
    zScore = sampleP95 === thresholdMs ? 0 : sampleP95 > thresholdMs ? Infinity : -Infinity;
    significantBreach = thresholdBreached ? true : false;
  } else if (standardErrorMs !== null && Number.isFinite(standardErrorMs) && standardErrorMs > 0) {
    zScore = (sampleP95 - thresholdMs) / standardErrorMs;
    if (thresholdBreached) {
      significantBreach = zScore >= criticalZ;
    } else {
      significantBreach = false;
    }
  }

  const inference: PerformanceInference = thresholdBreached
    ? significantBreach
      ? 'violates-target'
      : 'inconclusive'
    : 'meets-target';

  return {
    sampleP95,
    standardErrorMs,
    thresholdMs,
    thresholdBreached,
    significantBreach,
    zScore,
    inference,
  };
}
