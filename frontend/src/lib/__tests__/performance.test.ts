import { describe, expect, it } from 'vitest';
import { binomialAccuracyTest, bootstrapP95Delta } from '../performance';

function repeat(value: number, count: number): number[] {
  return Array.from({ length: count }, () => value);
}

function createRandomSequence(values: number[]): () => number {
  let index = 0;
  return () => {
    const value = values[index % values.length];
    index += 1;
    return value;
  };
}

describe('bootstrapP95Delta', () => {
  it('returns insufficient data when below the minimum sample size', () => {
    const result = bootstrapP95Delta({
      values: repeat(120, 40),
      thresholdMs: 150,
      alpha: 0.05,
      minSampleSize: 100,
      outlierThresholdMs: 1_000,
      resamples: 20,
      randomFn: createRandomSequence([0.1, 0.9, 0.3, 0.7]),
    });

    expect(result.inference).toBe('insufficient-data');
    expect(result.sampleP95).toBeNull();
  });

  it('labels performance as meeting the target when comfortably below the threshold', () => {
    const result = bootstrapP95Delta({
      values: [...repeat(120, 950), ...repeat(150, 200)],
      thresholdMs: 220,
      alpha: 0.05,
      minSampleSize: 500,
      outlierThresholdMs: 1_000,
      resamples: 40,
      randomFn: createRandomSequence([0.2, 0.8, 0.4, 0.6]),
    });

    expect(result.sampleP95).not.toBeNull();
    expect(result.deltaHigh).not.toBeNull();
    expect(result.deltaHigh ?? 1).toBeLessThanOrEqual(0);
    expect(result.inference).toBe('meet-target');
  });

  it('flags statistically significant breaches when the P95 is above the threshold', () => {
    const result = bootstrapP95Delta({
      values: [...repeat(320, 800), ...repeat(400, 400)],
      thresholdMs: 250,
      alpha: 0.05,
      minSampleSize: 500,
      outlierThresholdMs: 1_000,
      resamples: 40,
      randomFn: createRandomSequence([0.15, 0.35, 0.55, 0.75]),
    });

    expect(result.sampleP95).not.toBeNull();
    expect(result.deltaLow).not.toBeNull();
    expect(result.deltaLow ?? 0).toBeGreaterThan(0);
    expect(result.inference).toBe('above-target');
  });
});

describe('binomialAccuracyTest', () => {
  it('returns insufficient data when the sample is too small', () => {
    const result = binomialAccuracyTest({
      successes: 18,
      total: 20,
      threshold: 0.85,
      alpha: 0.05,
      minSampleSize: 50,
    });

    expect(result.inference).toBe('insufficient-data');
    expect(result.pValue).toBeNull();
  });

  it('flags regressions below the accuracy threshold', () => {
    const result = binomialAccuracyTest({
      successes: 50,
      total: 120,
      threshold: 0.85,
      alpha: 0.05,
      minSampleSize: 100,
    });

    expect(result.inference).toBe('below-target');
    expect(result.pValue).not.toBeNull();
    expect(result.pValue ?? 1).toBeLessThan(0.05);
  });

  it('passes when the observed accuracy meets the target', () => {
    const result = binomialAccuracyTest({
      successes: 115,
      total: 120,
      threshold: 0.85,
      alpha: 0.05,
      minSampleSize: 100,
    });

    expect(result.inference).toBe('meet-target');
    expect(result.pValue).not.toBeNull();
    expect(result.pValue ?? 0).toBeGreaterThanOrEqual(0.05);
  });
});
