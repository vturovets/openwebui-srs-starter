<script lang="ts">
  import type { HolidayResultEntry, MappedFilter } from '../lib/types';
  import { getExtractedValueRows } from '../lib/extractedValues';

  export let entry: HolidayResultEntry;

  const metadata = entry.result.metadata ?? {};
  const dataPayload = (entry.result.data ?? {}) as Record<string, unknown>;
  const timings = (metadata.timings ?? {}) as Record<string, unknown>;
  const missing = metadata.missingFields ?? [];
  const invalid = metadata.invalidFields ?? [];
  const mismatches = metadata.expectedValueMismatches ?? [];
  const mappedFilters = Array.isArray(entry.result.filters)
    ? (entry.result.filters as MappedFilter[])
    : [];

  const isPreferencesResult =
    typeof metadata.mode === 'string' && metadata.mode.trim().toLowerCase() === 'preferences';

  const emptyPreferencesMessage = (() => {
    if (!isPreferencesResult || mappedFilters.length > 0) {
      return '';
    }

    const metadataMessage = typeof metadata.message === 'string' ? metadata.message.trim() : '';
    if (metadataMessage) {
      return metadataMessage;
    }

    const statusLabel = typeof entry.result.status === 'string' ? entry.result.status.trim() : '';
    if (statusLabel.toLowerCase().includes('no-preferences')) {
      return 'No preferences detected from your input.';
    }

    return 'No preferences detected in your request.';
  })();

  const errorMessage = (() => {
    const metadataMessage = typeof metadata.message === 'string' ? metadata.message.trim() : '';
    if (metadataMessage) {
      return metadataMessage;
    }

    const dataError = dataPayload.error;
    if (typeof dataError === 'string') {
      const trimmed = dataError.trim();
      if (trimmed) {
        return trimmed;
      }
    }

    return '';
  })();

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

  function formatConfidence(value: unknown): string {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return '';
    }
    return `${formatNumber(value * 100)}%`;
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

  const formattedDataRows = getExtractedValueRows(entry);

  const rawStatus = typeof entry.result.status === 'string' ? entry.result.status : '';
  const normalizedStatus = rawStatus.trim().toLowerCase();
  const statusState = normalizedStatus
    ? ['success', 'ok', 'passed'].includes(normalizedStatus)
      ? 'success'
      : 'error'
    : 'idle';
  const statusLabel = normalizedStatus || 'pending';
</script>

<article class={`result ${entry.result.status}`} data-testid="structured-result">
  <header class="result-header">
    <div class="title-stack">
      <p class="result-overline">{entry.source === 'voice' ? 'Voice request' : 'Text request'}</p>
      <div class="title-row">
        <h2>{entry.source === 'voice' ? 'Voice request' : 'Text request'}</h2>
        <span class={`status-chip ${statusState}`} data-testid="status-label">
          Status: <span class="status-text">{statusLabel}</span>
        </span>
      </div>
    </div>
    <time datetime={entry.timestamp}>{new Date(entry.timestamp).toLocaleString()}</time>
  </header>

  {#if errorMessage || entry.prompt}
    <section class="status-banner">
      {#if errorMessage}
        <p class="error-message" data-testid="error-message">{errorMessage}</p>
      {/if}
      {#if entry.prompt}
        <div class="prompt" data-testid="clarification">
          <strong>Clarification needed:</strong>
          <pre>{entry.prompt}</pre>
        </div>
      {/if}
    </section>
  {/if}

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
      <colgroup>
        <col style="width: var(--label-column-width)" />
        <col />
      </colgroup>
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

  {#if mappedFilters.length}
    <section class="mapped-filters" data-testid="mapped-filters">
      <h3>Mapped filters</h3>
      {#each mappedFilters as filter, index (filter.filterId ?? filter.filterLabel ?? `filter-${index}`)}
        <div class="filter-group" data-testid="filter-group">
          <h4>{filter.filterLabel ?? filter.filterId}</h4>
          <ul>
            {#if (filter.options ?? []).length === 0}
              <li class="empty">No options mapped</li>
            {:else}
              {#each filter.options ?? [] as option, optionIndex (option.optionId ?? option.optionLabel ?? `option-${optionIndex}`)}
                <li class:selected={option.selected} class="filter-option" data-testid="filter-option">
                  <div class="option-row">
                    <span class="option-label">{option.optionLabel ?? option.optionId}</span>
                    {#if option.selected}
                      <span class="badge" aria-label="Selected option">Selected</span>
                    {/if}
                    {#if typeof option.confidence === 'number'}
                      <span class="confidence">{formatConfidence(option.confidence)}</span>
                    {/if}
                  </div>
                  {#if option.spans?.length}
                    <div class="span-hints">
                      {option.spans.map((span) => span.text).filter(Boolean).join(' · ')}
                    </div>
                  {/if}
                </li>
              {/each}
            {/if}
          </ul>
        </div>
      {/each}
    </section>
  {:else if emptyPreferencesMessage}
    <section class="mapped-filters empty" data-testid="mapped-filters-empty">
      <h3>Mapped filters</h3>
      <p>{emptyPreferencesMessage}</p>
    </section>
  {/if}

  {#if missing.length || invalid.length || mismatches.length}
    <section class="issues" data-testid="issue-summary">
      <h3>Validation summary</h3>
      {#if missing.length}
        <p><strong>Missing:</strong> {missing.join(', ')}</p>
      {/if}
      {#if invalid.length}
        <p><strong>Invalid:</strong> {invalid.join(', ')}</p>
      {/if}
      {#if mismatches.length}
        <div class="mismatches">
          <p><strong>Expected value mismatches:</strong></p>
          <ul>
            {#each mismatches as mismatch}
              <li>
                <strong>{mismatch.label}</strong>: expected “{mismatch.expected || '—'}” but got “
                {mismatch.actual || '—'}”.
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    </section>
  {/if}
</article>

<style>
  .result {
    background: linear-gradient(160deg, rgba(21, 33, 59, 0.75), rgba(12, 20, 38, 0.9));
    border-radius: 16px;
    padding: 1.1rem 1.25rem;
    display: grid;
    gap: 0.85rem;
    --label-column-width: clamp(8rem, 25vw, 13rem);
    border: 1px solid rgba(110, 143, 202, 0.3);
    box-shadow: 0 20px 45px rgba(0, 0, 0, 0.35);
  }

  .result.success {
    border-color: rgba(74, 222, 128, 0.35);
  }

  .result.failed,
  .result.error {
    border-color: rgba(248, 113, 113, 0.4);
  }

  .result-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
  }

  .title-stack {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .title-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .result-overline {
    margin: 0;
    font-size: 0.75rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #9cb1dc;
  }

  h2 {
    margin: 0;
    font-size: 1.2rem;
    letter-spacing: 0.01em;
  }

  time {
    font-size: 0.85rem;
    color: #9fb4dd;
    white-space: nowrap;
  }

  .status-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.75rem;
    border-radius: 999px;
    border: 1px solid rgba(148, 197, 250, 0.35);
    background: rgba(68, 111, 170, 0.2);
    font-weight: 700;
    color: #d0ddff;
  }

  .status-text {
    text-transform: capitalize;
  }

  .status-chip::before {
    content: '';
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: currentColor;
    box-shadow: 0 0 0 4px rgba(208, 221, 255, 0.18);
  }

  .status-chip.success {
    border-color: rgba(52, 211, 153, 0.35);
    background: rgba(34, 197, 94, 0.12);
    color: #5ce7b4;
  }

  .status-chip.error {
    border-color: rgba(248, 113, 113, 0.35);
    background: rgba(248, 113, 113, 0.12);
    color: #fca5a5;
  }

  .status-banner {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(148, 197, 250, 0.2);
    border-radius: 12px;
    padding: 0.75rem 0.9rem;
    display: grid;
    gap: 0.35rem;
  }

  .error-message {
    margin: 0;
    color: #fca5a5;
    font-size: 0.95rem;
  }

  .prompt {
    background: rgba(248, 113, 113, 0.15);
    border-radius: 10px;
    padding: 0.6rem 0.7rem;
    margin: 0;
  }

  .prompt pre {
    margin: 0.25rem 0 0;
    white-space: pre-wrap;
    font-size: 0.85rem;
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

  .request-text pre,
  .data,
  .timings,
  .mapped-filters,
  .issues {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(148, 197, 250, 0.2);
    border-radius: 12px;
    padding: 0.9rem 1rem;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
  }

  .request-text pre {
    margin: 0;
    font-size: 0.95rem;
    line-height: 1.5;
    color: #e6edff;
    white-space: pre-wrap;
    word-break: break-word;
    background: linear-gradient(135deg, rgba(22, 36, 63, 0.5), rgba(18, 28, 50, 0.7));
    border-radius: 10px;
    border: 1px solid rgba(104, 140, 214, 0.25);
  }

  .data ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.35rem;
    font-size: 0.9rem;
  }

  .data li {
    display: grid;
    grid-template-columns: minmax(6.5rem, var(--label-column-width)) 1fr;
    column-gap: 0.75rem;
    align-items: baseline;
  }

  .data strong {
    color: #9fb4dd;
    font-weight: 700;
  }

  .data span {
    display: block;
  }

  .timings h3,
  .data h3,
  .mapped-filters h3,
  .issues h3 {
    margin: 0 0 0.35rem;
    letter-spacing: 0.02em;
  }

  table {
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    font-size: 0.9rem;
    border: 1px solid rgba(148, 197, 250, 0.2);
    border-radius: 12px;
    overflow: hidden;
    background: rgba(8, 12, 24, 0.35);
  }

  th,
  td {
    padding: 0.45rem 0.6rem;
    text-align: left;
    border-bottom: 1px solid rgba(148, 163, 184, 0.25);
  }

  th {
    color: #9fb4dd;
    font-weight: 700;
    padding-right: 1rem;
  }

  td {
    width: auto;
    color: #e6edff;
  }

  tr:last-child th,
  tr:last-child td {
    border-bottom: none;
  }

  .mapped-filters {
    display: grid;
    gap: 0.75rem;
    background: linear-gradient(135deg, rgba(16, 26, 46, 0.8), rgba(18, 31, 55, 0.75));
  }

  .mapped-filters.empty {
    color: #cbd5e1;
  }

  .mapped-filters.empty p {
    margin: 0;
  }

  .filter-group {
    display: grid;
    gap: 0.5rem;
  }

  .filter-group h4 {
    margin: 0;
  }

  .filter-group ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.5rem;
  }

  .filter-option {
    background: rgba(12, 20, 38, 0.7);
    border-radius: 10px;
    padding: 0.6rem 0.8rem;
    display: grid;
    gap: 0.25rem;
    border: 1px solid rgba(148, 197, 250, 0.18);
  }

  .filter-option.selected {
    border-color: #5ab7ff;
    box-shadow: 0 12px 20px rgba(90, 183, 255, 0.12);
  }

  .option-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .option-label {
    font-weight: 700;
  }

  .span-hints {
    color: #cbd5e1;
    font-size: 0.9rem;
  }

  .badge {
    background: #5ab7ff;
    color: #0b1224;
    border-radius: 999px;
    padding: 0.15rem 0.5rem;
    font-size: 0.8rem;
    font-weight: 700;
  }

  .confidence {
    color: #9fb4dd;
    font-size: 0.85rem;
  }

  .mismatches ul {
    margin: 0.25rem 0 0;
    padding-left: 1.25rem;
  }

  .mismatches li {
    margin-bottom: 0.25rem;
    font-size: 0.9rem;
  }

  .issues p {
    margin: 0.25rem 0 0;
    font-size: 0.9rem;
  }
</style>

