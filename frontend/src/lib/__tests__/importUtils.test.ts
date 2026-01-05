import { describe, expect, it } from 'vitest';
import {
  compareExpectedPreferences,
  compareExpectedValues,
  parseExpectedPreferences,
  parseExpectedValues,
} from '../importUtils';
import type { ExtractedValueRow } from '../extractedValues';
import type { MappedFilter } from '../types';

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

  it('parses expected preference filters from CR-004 format', () => {
    const values = parseExpectedPreferences(
      'Language: en | Filter: "Facilities"; Options: "Scuba", "Scuba - additional info" | Filter: "Boards"; Options: "Room Only"'
    );

    expect(values).toEqual([
      { filterLabel: 'Facilities', options: ['Scuba', 'Scuba - additional info'] },
      { filterLabel: 'Boards', options: ['Room Only'] },
    ]);
  });

  it('compares expected preference filters with actual filter mappings', () => {
    const actualFilters: MappedFilter[] = [
      {
        filterId: 'facilities',
        filterLabel: 'Facilities',
        options: [
          { optionId: 'scuba', optionLabel: 'Scuba', selected: true },
          { optionId: 'wifi', optionLabel: 'Wi-Fi', selected: false },
        ],
      },
      {
        filterId: 'boards',
        filterLabel: 'Boards',
        options: [{ optionId: 'room-only', optionLabel: 'Room Only', selected: true }],
      },
    ];

    const expected = parseExpectedPreferences(
      'Filter: "Facilities"; Options: "Scuba", "Scuba - additional info" | Filter: "Boards"; Options: "Room Only"'
    );

    const mismatches = compareExpectedPreferences(actualFilters, expected);
    expect(mismatches).toEqual([
      {
        label: 'Filter: "Facilities"',
        expected: 'Options: "Scuba", "Scuba - additional info"',
        actual: 'Options: "Scuba"',
      },
    ]);
  });
});
