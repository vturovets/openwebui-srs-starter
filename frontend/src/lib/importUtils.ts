import type { ExtractedValueRow } from './extractedValues';
import type { MappedFilter } from './types';

export type ExpectedValue = { label: string; value: string };
export type ExpectedValueMismatch = { label: string; expected: string; actual: string };
export type ExpectedPreference = { filterLabel: string; options: string[] };

function normalisePart(value: string): string {
  return value.trim();
}

function stripWrappingQuotes(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function normalisePreferenceToken(value: string): string {
  return stripWrappingQuotes(value).trim();
}

function parsePreferenceOptions(raw: string): string[] {
  const trimmed = raw.trim();
  if (!trimmed) {
    return [];
  }

  const quotedMatches = Array.from(trimmed.matchAll(/"([^"]*)"/g)).map((match) =>
    match[1].trim()
  );
  if (quotedMatches.length) {
    return quotedMatches.map(normalisePreferenceToken).filter(Boolean);
  }

  return trimmed
    .split(',')
    .map((segment) => normalisePreferenceToken(segment))
    .filter(Boolean);
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

export function parseExpectedPreferences(raw: string): ExpectedPreference[] {
  if (!raw) {
    return [];
  }

  return raw
    .split('|')
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map((segment) => {
      const filterMatch = segment.match(/filter\s*:\s*([^;]+)(?:;|$)/i);
      if (!filterMatch) {
        return null;
      }
      const filterLabel = normalisePreferenceToken(filterMatch[1]);
      const optionsMatch = segment.match(/options\s*:\s*(.*)$/i);
      const options = parsePreferenceOptions(optionsMatch?.[1] ?? '');
      return { filterLabel, options };
    })
    .filter((entry): entry is ExpectedPreference => Boolean(entry?.filterLabel));
}

function collectPreferenceOptions(options: string[]) {
  const optionMap = new Map<string, string>();
  options.forEach((option) => {
    const normalized = normalisePreferenceToken(option);
    if (!normalized) {
      return;
    }
    const key = normalized.toLowerCase();
    if (!optionMap.has(key)) {
      optionMap.set(key, normalized);
    }
  });

  const ordered = Array.from(optionMap.values()).sort((a, b) => a.localeCompare(b));
  return {
    normalized: new Set(optionMap.keys()),
    display: ordered,
  };
}

function formatPreferenceOptions(options: string[]): string {
  if (!options.length) {
    return '';
  }
  const list = options.map((option) => `"${option}"`).join(', ');
  return `Options: ${list}`;
}

function buildPreferenceMap(filters: Array<{ label: string; options: string[] }>) {
  const map = new Map<
    string,
    { label: string; options: ReturnType<typeof collectPreferenceOptions> }
  >();

  filters.forEach(({ label, options }) => {
    const normalizedLabel = normalisePreferenceToken(label);
    if (!normalizedLabel) {
      return;
    }
    const key = normalizedLabel.toLowerCase();
    const existing = map.get(key);
    const collected = collectPreferenceOptions(options);
    if (existing) {
      collected.display.forEach((option) => {
        if (!existing.options.normalized.has(option.toLowerCase())) {
          existing.options.normalized.add(option.toLowerCase());
          existing.options.display.push(option);
        }
      });
      existing.options.display.sort((a, b) => a.localeCompare(b));
      return;
    }
    map.set(key, { label: normalizedLabel, options: collected });
  });

  return map;
}

function setEquals(left: Set<string>, right: Set<string>): boolean {
  if (left.size !== right.size) {
    return false;
  }
  for (const value of left) {
    if (!right.has(value)) {
      return false;
    }
  }
  return true;
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

export function compareExpectedPreferences(
  actualFilters: MappedFilter[],
  expectedFilters: ExpectedPreference[]
): ExpectedValueMismatch[] {
  if (!expectedFilters.length) {
    return [];
  }

  const expectedMap = buildPreferenceMap(
    expectedFilters.map(({ filterLabel, options }) => ({
      label: filterLabel,
      options,
    }))
  );
  const actualMap = buildPreferenceMap(
    actualFilters.map((filter) => ({
      label: filter.filterLabel ?? filter.filterId ?? '',
      options: (filter.options ?? [])
        .filter((option) => option.selected !== false)
        .map((option) => option.optionLabel ?? option.optionId ?? ''),
    }))
  );

  const mismatches: ExpectedValueMismatch[] = [];
  expectedMap.forEach((expected, key) => {
    const actual = actualMap.get(key);
    const actualOptions = actual?.options.normalized ?? new Set<string>();
    if (!setEquals(expected.options.normalized, actualOptions)) {
      mismatches.push({
        label: `Filter: "${expected.label}"`,
        expected: formatPreferenceOptions(expected.options.display),
        actual: formatPreferenceOptions(actual?.options.display ?? []),
      });
    }
  });

  actualMap.forEach((actual, key) => {
    if (!expectedMap.has(key) && actual.options.normalized.size > 0) {
      mismatches.push({
        label: `Filter: "${actual.label}"`,
        expected: '',
        actual: formatPreferenceOptions(actual.options.display),
      });
    }
  });

  return mismatches;
}
