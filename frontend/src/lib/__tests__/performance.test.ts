import { describe, expect, it } from 'vitest';
import { evaluateAccuracy, evaluateP95Performance, filterResponseTimes } from '../performance';

function repeat(value: number, count: number): number[] {
  return Array.from({ length: count }, () => value);
}

describe('filterResponseTimes', () => {
  it('filters out non-numeric, negative and outlier values', () => {
    const cleaned = filterResponseTimes([120, null as unknown as number, -5, 10_500, 750], 10_000);

    expect(cleaned).toEqual([120, 750]);
  });
});

describe('evaluateP95Performance', () => {
  it('returns insufficient data when below the minimum sample size', () => {
    const result = evaluateP95Performance({
      values: repeat(120, 40),
      thresholdMs: 150,
      minSampleSize: 100,
      alpha: 0.05,
    });

    expect(result.inference.outcome).toBe('insufficient-data');
    expect(result.sampleP95).toBe(120);
  });

  it('labels performance as meeting the target when below the threshold', () => {
    const values = [...repeat(120, 950), ...repeat(150, 50)];
    const result = evaluateP95Performance({
      values,
      thresholdMs: 200,
      minSampleSize: 100,
      alpha: 0.05,
    });

    expect(result.inference.outcome).toBe('meets-target');
  });

  it('flags regressions when the P95 clearly exceeds the target', () => {
    const values = Array.from({ length: 400 }, (_, index) => 150 + index);
    const result = evaluateP95Performance({
      values,
      thresholdMs: 250,
      minSampleSize: 200,
      alpha: 0.05,
    });

    expect(result.inference.outcome).toBe('above-target');
    expect(result.inference.confidence).not.toBeNull();
  });
});

describe('evaluateAccuracy', () => {
  it('detects accuracy drops below the threshold', () => {
    const result = evaluateAccuracy({
      successes: 820,
      trials: 1000,
      target: 0.9,
      minSampleSize: 500,
      alpha: 0.05,
    });

    expect(result.inference.outcome).toBe('below-target');
    expect(result.inference.confidence).toBeGreaterThan(0.9);
  });

  it('reports insufficient data for small samples', () => {
    const result = evaluateAccuracy({
      successes: 9,
      trials: 10,
      target: 0.85,
      minSampleSize: 100,
      alpha: 0.05,
    });

    expect(result.inference.outcome).toBe('insufficient-data');
  });
});
