export type InferenceOutcome = 'meets-target' | 'above-target' | 'below-target' | 'insufficient-data';

export type MetricInference = {
  outcome: InferenceOutcome;
  confidence: number | null;
  pValue: number | null;
};

export type P95Assessment = {
  sampleP95: number | null;
  thresholdMs: number;
  sampleSize: number;
  successes: number;
  inference: MetricInference;
};

export type AccuracyAssessment = {
  accuracy: number;
  threshold: number;
  sampleSize: number;
  successes: number;
  inference: MetricInference;
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

export function filterResponseTimes(values: number[], outlierThresholdMs: number): number[] {
  return values.filter((value) => Number.isFinite(value) && value >= 0 && value <= outlierThresholdMs);
}

function binomialCdf(successes: number, trials: number, probability: number): number {
  if (trials === 0) {
    return 1;
  }
  if (probability === 0) {
    return successes === 0 ? 1 : 0;
  }
  if (probability === 1) {
    return successes === trials ? 1 : 0;
  }
  if (successes >= trials) {
    return 1;
  }

  const failureProbability = 1 - probability;
  let probabilityMass = failureProbability ** trials;
  let cumulative = probabilityMass;

  for (let i = 1; i <= successes; i += 1) {
    probabilityMass *= (probability / failureProbability) * ((trials - i + 1) / i);
    cumulative += probabilityMass;
  }

  return Math.min(1, cumulative);
}

function buildInference(outcome: InferenceOutcome, pValue: number | null): MetricInference {
  const confidence = pValue === null ? null : Math.max(0, Math.min(1, 1 - pValue));
  return { outcome, pValue, confidence };
}

export function evaluateP95Performance({
  values,
  thresholdMs,
  minSampleSize,
  alpha,
  percentile = 0.95,
}: {
  values: number[];
  thresholdMs: number;
  minSampleSize: number;
  alpha: number;
  percentile?: number;
}): P95Assessment {
  const sampleSize = values.length;
  const sampleP95 = sampleSize ? getQuantile(cloneAndSort(values), percentile) : null;
  const successes = values.filter((value) => value <= thresholdMs).length;

  if (sampleSize < minSampleSize) {
    return {
      sampleP95,
      thresholdMs,
      sampleSize,
      successes,
      inference: buildInference('insufficient-data', null),
    };
  }

  const pValue = binomialCdf(successes, sampleSize, percentile);
  const outcome: InferenceOutcome = pValue < alpha ? 'above-target' : 'meets-target';

  return {
    sampleP95,
    thresholdMs,
    sampleSize,
    successes,
    inference: buildInference(outcome, pValue),
  };
}

export function evaluateAccuracy({
  successes,
  trials,
  target,
  minSampleSize,
  alpha,
}: {
  successes: number;
  trials: number;
  target: number;
  minSampleSize: number;
  alpha: number;
}): AccuracyAssessment {
  if (trials < 0 || successes < 0 || successes > trials) {
    throw new Error('Invalid accuracy sample sizes');
  }
  const accuracy = trials > 0 ? successes / trials : 0;

  if (trials < minSampleSize) {
    return {
      accuracy,
      threshold: target,
      sampleSize: trials,
      successes,
      inference: buildInference('insufficient-data', null),
    };
  }

  const pValue = binomialCdf(successes, trials, target);
  const outcome: InferenceOutcome = pValue < alpha ? 'below-target' : 'meets-target';

  return {
    accuracy,
    threshold: target,
    sampleSize: trials,
    successes,
    inference: buildInference(outcome, pValue),
  };
}
