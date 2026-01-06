import airportsFixture from '../../../fixtures/airports.json';
import destinationsFixture from '../../../fixtures/destinations.json';
import configurationSearchFixture from '../../../fixtures/configuration_search.json';
import type { HolidayResultEntry } from './types';

export type ExtractedValueRow = { label: string; value: string };

type Airport = { id: string; name: string };
type Destination = { id: string; name: string; type?: string | null };
type Duration = { id: string; name: string };

const airportNameById = new Map<string, string>(
  ((airportsFixture as { data?: { airports?: Airport[] } }).data?.airports ?? []).map(
    ({ id, name }) => [id, name]
  )
);

const destinationNameById = (() => {
  const map = new Map<string, string>();
  const groups = (destinationsFixture as { data?: Record<string, Destination[]> }).data ?? {};

  Object.values(groups).forEach((destinations) => {
    destinations.forEach(({ id, name, type }) => {
      map.set(id, name);
      if (type) {
        map.set(`${id}:${type}`, name);
      }
    });
  });

  return map;
})();

const durationNameById = new Map<string, string>(
  (
    (configurationSearchFixture as {
      holidaySearchConfiguration?: { durations?: Duration[] };
    }).holidaySearchConfiguration?.durations ?? []
  ).map(({ id, name }) => [id, name])
);

const LABELS: Record<string, string> = {
  language: 'Language',
  from: 'From',
  to: 'To',
  departureDate: 'Departure date range',
  durationId: 'Duration',
  party: 'Participants',
  rooms: 'Rooms',
};

const ORDER = ['language', 'from', 'to', 'departureDate', 'durationId', 'party', 'rooms'];

const MAX_DECIMALS = 2;

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return value.toString();
  }
  return Number(value.toFixed(MAX_DECIMALS)).toString();
}

function numberReplacer(_key: string, value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Number(value.toFixed(MAX_DECIMALS));
  }
  return value;
}

function humanizeKey(key: string): string {
  return key
    .replace(/([A-Z])/g, ' $1')
    .split(' ')
    .map((part, index) =>
      index === 0 ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : part.toLowerCase()
    )
    .join(' ');
}

function formatValue(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return formatNumber(value);
  }
  if (Array.isArray(value) || (value && typeof value === 'object')) {
    return JSON.stringify(value, numberReplacer);
  }
  if (value === null) {
    return 'null';
  }
  if (value === undefined) {
    return '';
  }
  return String(value);
}

function formatAirportList(value: unknown): string {
  if (Array.isArray(value)) {
    if (!value.length) {
      return '';
    }
    return value
      .map((item) => (typeof item === 'string' ? airportNameById.get(item) ?? item : formatValue(item)))
      .join(', ');
  }
  if (typeof value === 'string') {
    return airportNameById.get(value) ?? value;
  }
  return formatValue(value);
}

function formatDestinationList(value: unknown): string {
  if (Array.isArray(value)) {
    if (!value.length) {
      return '';
    }
    return value
      .map((item) =>
        typeof item === 'string' ? destinationNameById.get(item) ?? item : formatValue(item)
      )
      .join(', ');
  }
  if (typeof value === 'string') {
    return destinationNameById.get(value) ?? value;
  }
  return formatValue(value);
}

function formatDateRange(value: unknown): string {
  if (Array.isArray(value) && value.every((item) => typeof item === 'string')) {
    return value.join(', ');
  }
  return formatValue(value);
}

function formatDuration(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number') {
    const duration = durationNameById.get(String(value));
    if (duration) {
      return duration;
    }
  }
  return formatValue(value);
}

function formatParticipants(value: unknown): string {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, count]) => typeof count === 'number' && count > 0)
      .map(([key, count]) => `${humanizeKey(key)}: ${formatNumber(count as number)}`);

    if (entries.length) {
      return entries.join(', ');
    }
  }
  return formatValue(value);
}

function formatRooms(value: unknown): string {
  if (value === null || value === undefined) {
    return 'Auto allocation';
  }
  if (typeof value === 'string') {
    const normalised = value.trim().toLowerCase();
    if (normalised === 'autoallocation' || normalised === 'auto_allocation') {
      return 'Auto allocation';
    }
  }
  return formatValue(value);
}

function formatValueByKey(key: string, value: unknown): string {
  switch (key) {
    case 'language':
      return typeof value === 'string' ? value : formatValue(value);
    case 'from':
      return formatAirportList(value);
    case 'to':
      return formatDestinationList(value);
    case 'departureDate':
      return formatDateRange(value);
    case 'durationId':
      return formatDuration(value);
    case 'party':
      return formatParticipants(value);
    case 'rooms':
      return formatRooms(value);
    default:
      return formatValue(value);
  }
}

function isPreferencesEntry(entry: HolidayResultEntry): boolean {
  const metadataMode =
    typeof entry.result.metadata?.mode === 'string'
      ? entry.result.metadata.mode.trim().toLowerCase()
      : '';
  if (metadataMode === 'preferences') {
    return true;
  }

  return Array.isArray(entry.result.filters);
}

function normalisePreferenceLabel(value: string): string {
  return value.trim().replace(/^["']|["']$/g, '');
}

function formatPreferenceRow(
  filterLabel: string,
  options: string[]
): ExtractedValueRow {
  const uniqueOptions = Array.from(
    new Set(options.map((option) => normalisePreferenceLabel(option)).filter(Boolean))
  ).sort((a, b) => a.localeCompare(b));
  const formattedOptions = uniqueOptions.join(', ');
  const optionsSegment = formattedOptions ? ` Options: ${formattedOptions}` : ' Options:';
  return {
    label: 'Filter',
    value: `${normalisePreferenceLabel(filterLabel)};${optionsSegment}`,
  };
}

export function getExtractedValueRows(entry: HolidayResultEntry): ExtractedValueRow[] {
  if (isPreferencesEntry(entry)) {
    const filters = Array.isArray(entry.result.filters) ? entry.result.filters : [];
    return filters.map((filter) => {
      const label = filter.filterLabel ?? filter.filterId ?? '';
      const options = (filter.options ?? [])
        .filter((option) => option.selected !== false)
        .map((option) => option.optionLabel ?? option.optionId ?? '')
        .filter(Boolean);
      return formatPreferenceRow(label, options);
    });
  }

  const data = (entry.result.data ?? {}) as Record<string, unknown>;
  const seen = new Set<string>();
  const rows: ExtractedValueRow[] = [];

  ORDER.forEach((key) => {
    if (key in data) {
      seen.add(key);
      rows.push({
        label: LABELS[key] ?? key,
        value: formatValueByKey(key, data[key]),
      });
    }
  });

  Object.entries(data).forEach(([key, value]) => {
    if (!seen.has(key)) {
      rows.push({
        label: LABELS[key] ?? key,
        value: formatValueByKey(key, value),
      });
    }
  });

  return rows;
}
