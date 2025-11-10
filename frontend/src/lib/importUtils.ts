import type { ExtractedValueRow } from './extractedValues';

export type ExpectedValue = { label: string; value: string };
export type ExpectedValueMismatch = { label: string; expected: string; actual: string };

function normalisePart(value: string): string {
  return value.trim();
}

export function parseExpectedValues(raw: string): ExpectedValue[] {
  if (!raw) {
    return [];
  }

  return raw
    .split('|')
    .map((segment) => {
      const piece = segment.trim();
      if (!piece) {
        return null;
      }
      const separatorIndex = piece.indexOf(':');
      if (separatorIndex === -1) {
        return { label: normalisePart(piece), value: '' };
      }
      const label = normalisePart(piece.slice(0, separatorIndex));
      const value = normalisePart(piece.slice(separatorIndex + 1));
      return { label, value };
    })
    .filter((entry): entry is ExpectedValue => Boolean(entry?.label));
}

export function compareExpectedValues(
  actualRows: ExtractedValueRow[],
  expectedValues: ExpectedValue[]
): ExpectedValueMismatch[] {
  if (!expectedValues.length) {
    return [];
  }

  const actualMap = new Map<string, string>();
  actualRows.forEach(({ label, value }) => {
    actualMap.set(label.trim(), value.trim());
  });

  const expectedMap = new Map<string, string>();
  expectedValues.forEach(({ label, value }) => {
    expectedMap.set(label.trim(), value.trim());
  });

  const mismatches: ExpectedValueMismatch[] = [];
  expectedMap.forEach((expected, label) => {
    const actual = actualMap.get(label) ?? '';
    if (actual !== expected) {
      mismatches.push({ label, expected, actual });
    }
  });

  actualMap.forEach((actual, label) => {
    if (!expectedMap.has(label) && actual) {
      mismatches.push({ label, expected: '', actual });
    }
  });

  return mismatches;
}
