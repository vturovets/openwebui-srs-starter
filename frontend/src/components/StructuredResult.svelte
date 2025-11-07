<script lang="ts">
  import type { HolidayResultEntry } from '../lib/types';

  export let entry: HolidayResultEntry;

  const metadata = entry.result.metadata ?? {};
  const timings = (metadata.timings ?? {}) as Record<string, unknown>;
  const missing = metadata.missingFields ?? [];
  const invalid = metadata.invalidFields ?? [];

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

  const MAX_DECIMALS = 3;

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
      <h3>Structured parameters</h3>
      <ul>
        {#each Object.entries(entry.result.data || {}) as [key, value]}
          <li><strong>{key}</strong> <span>{formatValue(value)}</span></li>
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

