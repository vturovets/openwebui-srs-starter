import { describe, expect, it } from 'vitest';
import { parseCsv, parseCsvForTesting } from '../csv';

describe('parseCsv', () => {
  it('splits CSV content with quoted fields', () => {
    const rows = parseCsvForTesting('"User input","Expected values"\n"Find a trip","From: AMS"\n');
    expect(rows).toEqual([
      ['User input', 'Expected values'],
      ['Find a trip', 'From: AMS'],
    ]);
  });

  it('returns normalised records from CSV text', () => {
    const content = '\ufeffUser input,Expected values\n"Find a trip","From: AMS"\n"Second",""\n';
    const records = parseCsv(content);
    expect(records).toEqual([
      {
        'User input': 'Find a trip',
        'Expected values': 'From: AMS',
      },
      {
        'User input': 'Second',
        'Expected values': '',
      },
    ]);
  });
});
