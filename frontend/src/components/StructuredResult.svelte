<script lang="ts">
  import airportsFixture from '../../../fixtures/airports.json';
  import destinationsFixture from '../../../fixtures/destinations.json';
  import configurationSearchFixture from '../../../fixtures/configuration_search.json';
  import type { HolidayResultEntry } from '../lib/types';

  export let entry: HolidayResultEntry;

  type Airport = { id: string; name: string };
  type Destination = { id: string; name: string; type?: string | null };
  type Duration = { id: string; name: string };

  const metadata = entry.result.metadata ?? {};
  const timings = (metadata.timings ?? {}) as Record<string, unknown>;
  const missing = metadata.missingFields ?? [];
  const invalid = metadata.invalidFields ?? [];

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

  function getNumericTiming(key: string): number | undefined {
    const value = timings[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
  }

  const timingRows = (() => {
    const networkLatencyMs =
      getNumericTiming('llmNetworkMs') ??
      getNumericTiming('networkLatencyMs') ??
      getNumericTiming('networkMs');

    return [
      {
        label: 'Language detection, ms',
        value: getNumericTiming('languageMs') ?? '',
      },
      {
        label: 'Extraction, ms',
        value: getNumericTiming('extractionMs') ?? '',
      },
      {
        label: 'Mapping to API request parameters, ms',
        value: getNumericTiming('normalizationMs') ?? '',
      },
      {
        label: 'Validation, ms',
        value: getNumericTiming('validationMs') ?? '',
      },
      {
        label: 'Transcription, ms',
        value: getNumericTiming('sttMs') ?? '',
      },
      {
        label: 'Network latency, ms',
        value: networkLatencyMs ?? '',
      },
    ];
  })();

  const totalTimingMs = timingRows.reduce((sum, row) => {
    return sum + (typeof row.value === 'number' ? row.value : 0);
  }, 0);

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
        .map((item) => (typeof item === 'string' ? destinationNameById.get(item) ?? item : formatValue(item)))
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

  function humanizeKey(key: string): string {
    return key
      .replace(/([A-Z])/g, ' $1')
      .split(' ')
      .map((part, index) =>
        index === 0 ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : part.toLowerCase()
      )
      .join(' ');
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

  const formattedDataRows = (() => {
    const data = (entry.result.data ?? {}) as Record<string, unknown>;
    const seen = new Set<string>();
    const rows: Array<{ label: string; value: string }> = [];

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
  })();
</script>

<article class={`result ${entry.result.status}`} data-testid="structured-result">
  <header>
    <h2>{entry.source === 'voice' ? 'Voice' : 'Text'} request</h2>
    <time datetime={entry.timestamp}>{new Date(entry.timestamp).toLocaleString()}</time>
  </header>
  <section class="status">
    <strong>Status:</strong>
    <span data-testid="status-label">{entry.result.status}</span>
    {#if entry.prompt}
      <div class="prompt" data-testid="clarification">
        <strong>Clarification needed:</strong>
        <pre>{entry.prompt}</pre>
      </div>
    {/if}
  </section>

  <section class="request-details">
    <div class="request-text">
      <h3>User input</h3>
      <pre>{entry.input}</pre>
    </div>

    <section class="data">
      <h3>API request parameters</h3>
      <ul>
        {#each formattedDataRows as { label, value }}
          <li><strong>{label}</strong> <span>{value}</span></li>
        {/each}
      </ul>
    </section>
  </section>

  <section class="timings">
    <h3>Timings</h3>
    <table>
      <tbody>
        {#each timingRows as { label, value }}
          <tr>
            <th>{label}</th>
            <td>{formatValue(value)}</td>
          </tr>
        {/each}
        <tr>
          <th>Total, ms</th>
          <td>{formatValue(totalTimingMs)}</td>
        </tr>
      </tbody>
    </table>
  </section>

  {#if missing.length || invalid.length}
    <section class="issues" data-testid="issue-summary">
      <h3>Validation summary</h3>
      {#if missing.length}
        <p><strong>Missing:</strong> {missing.join(', ')}</p>
      {/if}
      {#if invalid.length}
        <p><strong>Invalid:</strong> {invalid.join(', ')}</p>
      {/if}
    </section>
  {/if}
</article>

<style>
  .result {
    background: rgba(15, 23, 42, 0.6);
    border-radius: 12px;
    padding: 1rem;
    display: grid;
    gap: 0.75rem;
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  h2 {
    margin: 0;
    font-size: 1.1rem;
  }

  time {
    font-size: 0.75rem;
    color: #94a3b8;
  }

  .status strong {
    margin-right: 0.5rem;
  }

  .status span {
    text-transform: capitalize;
  }

  .result.success {
    border: 1px solid rgba(74, 222, 128, 0.3);
  }

  .result.failed,
  .result.error {
    border: 1px solid rgba(248, 113, 113, 0.3);
  }

  .request-details {
    display: grid;
    gap: 1rem;
  }

  @media (min-width: 768px) {
    .request-details {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      align-items: start;
    }
  }

  .request-text pre {
    margin: 0;
    padding: 0.75rem;
    background: rgba(51, 65, 85, 0.5);
    border-radius: 8px;
    font-size: 0.9rem;
    line-height: 1.4;
    color: #e2e8f0;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .data ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.25rem;
    font-size: 0.8rem;
  }

  .data li {
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
  }

  .data strong {
    min-width: 120px;
    color: #94a3b8;
    font-weight: 600;
  }

  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.8rem;
  }

  th,
  td {
    padding: 0.25rem 0.5rem;
    text-align: left;
    border-bottom: 1px solid rgba(148, 163, 184, 0.3);
  }

  .prompt {
    background: rgba(248, 113, 113, 0.15);
    border-radius: 8px;
    padding: 0.5rem;
    margin-top: 0.5rem;
  }

  .prompt pre {
    margin: 0;
    white-space: pre-wrap;
    font-size: 0.75rem;
  }

  .issues p {
    margin: 0.25rem 0 0;
    font-size: 0.8rem;
  }
</style>

