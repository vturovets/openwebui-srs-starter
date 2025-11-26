import { describe, expect, it } from 'vitest';
import { assessP95Threshold } from '../performance';

function repeat(value: number, count: number): number[] {
  return Array.from({ length: count }, () => value);
}

describe('assessP95Threshold', () => {
  it('returns null when below the minimum sample size', () => {
    const values = repeat(120, 40);
    const result = assessP95Threshold({
      values,
      requestCount: 40,
      thresholdMs: 150,
      sampleSize: 100,
      alpha: 0.05,
    });

    expect(result).toBeNull();
  });

  it('labels performance as meeting the target when comfortably below the threshold', () => {
    const values = [...repeat(120, 950), ...repeat(150, 50)];
    const result = assessP95Threshold({
      values,
      requestCount: values.length,
      thresholdMs: 200,
      sampleSize: 100,
      alpha: 0.05,
    });

    expect(result).not.toBeNull();
    expect(result!.thresholdBreached).toBe(false);
    expect(result!.inference).toBe('meets-target');
  });

  it('marks breaches as inconclusive when the threshold is only marginally exceeded', () => {
    const values = Array.from({ length: 200 }, (_, index) => 100 + index);
    const result = assessP95Threshold({
      values,
      requestCount: values.length,
      thresholdMs: 288,
      sampleSize: 50,
      alpha: 0.05,
    });

    expect(result).not.toBeNull();
    expect(result!.thresholdBreached).toBe(true);
    expect(result!.inference).toBe('inconclusive');
  });

  it('flags statistically significant breaches', () => {
    const values = [...repeat(120, 800), ...repeat(220, 200)];
    const result = assessP95Threshold({
      values,
      requestCount: values.length,
      thresholdMs: 180,
      sampleSize: 100,
      alpha: 0.05,
    });

    expect(result).not.toBeNull();
    expect(result!.thresholdBreached).toBe(true);
    expect(result!.inference).toBe('violates-target');
    expect(result!.significantBreach).toBe(true);
  });
});
