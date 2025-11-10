import { describe, expect, it } from 'vitest';
import { compareExpectedValues, parseExpectedValues } from '../importUtils';
import type { ExtractedValueRow } from '../extractedValues';

describe('importUtils', () => {
  it('parses expected values from export-style strings', () => {
    const values = parseExpectedValues('From: Amsterdam | To: Italy | Duration: 7 nights');
    expect(values).toEqual([
      { label: 'From', value: 'Amsterdam' },
      { label: 'To', value: 'Italy' },
      { label: 'Duration', value: '7 nights' },
    ]);
  });

  it('identifies mismatches between expected and actual values', () => {
    const actualRows: ExtractedValueRow[] = [
      { label: 'From', value: 'Amsterdam' },
      { label: 'To', value: 'Italy' },
      { label: 'Duration', value: '10 nights' },
    ];
    const expected = parseExpectedValues('From: Amsterdam | To: Spain | Duration: 7 nights');
    const mismatches = compareExpectedValues(actualRows, expected);

    expect(mismatches).toEqual([
      { label: 'To', expected: 'Spain', actual: 'Italy' },
      { label: 'Duration', expected: '7 nights', actual: '10 nights' },
    ]);
  });
});
