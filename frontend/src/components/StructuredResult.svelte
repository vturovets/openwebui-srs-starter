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

  function toFiniteNumber(value: unknown): number | undefined {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) {
        return undefined;
      }
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? parsed : undefined;
    }
    return undefined;
  }

  function getNumericTiming(...keys: string[]): number | undefined {
    for (const key of keys) {
      const candidate = toFiniteNumber(timings[key]);
      if (candidate !== undefined) {
        return candidate;
      }
    }
    return undefined;
  }

  const timingRows = (() => {
    return [
      {
        label: 'Language detection, ms',
        value: getNumericTiming('languageMs', 'languageDetectionMs', 'language') ?? '',
      },
      {
        label: 'Extraction, ms',
        value: getNumericTiming('extractionMs', 'extraction') ?? '',
      },
      {
        label: 'Mapping to API request parameters, ms',
        value:
          getNumericTiming('normalizationMs', 'normalisationMs', 'mappingMs', 'mapping') ?? '',
      },
      {
        label: 'Validation, ms',
        value: getNumericTiming('validationMs', 'validation') ?? '',
      },
      {
        label: 'Transcription, ms',
        value: getNumericTiming('sttMs', 'transcriptionMs', 'voiceMs') ?? '',
      },
      {
        label: 'Network latency, ms',
        value:
          getNumericTiming('networkLatencyMs', 'llmNetworkMs', 'networkMs', 'network') ?? '',
      },
    ];
  })();

  const summedTimingMs = timingRows.reduce((sum, row) => {
    return sum + (typeof row.value === 'number' ? row.value : 0);
  }, 0);

  const totalTimingMs =
    getNumericTiming('totalTimingMs', 'totalMs', 'total', 'totalMilliseconds') ?? summedTimingMs;

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
</script>

<article class={`result ${entry.result.status}`} data-testid="structured-result">
  <header>
    <h2>{entry.source === 'voice' ? 'Voice' : 'Text'} request</h2>
    <time datetime={entry.timestamp}>{new Date(entry.timestamp).toLocaleString()}</time>
  </header>
  <section class="status">
    <strong>Status:</strong>
    <span data-testid="status-label">{entry.result.status}</span>
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

  <section class="request-details">
    <div class="request-text">
      <h3>User input</h3>
      <pre>{entry.input}</pre>
    </div>

    {#if !isPreferencesResult}
      <section class="data">
        <h3>API request parameters</h3>
        <ul>
          {#each formattedDataRows as { label, value }}
            <li><strong>{label}</strong> <span>{value}</span></li>
          {/each}
        </ul>
      </section>
    {/if}
  </section>

  <section class="details-grid">
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
  </section>

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
    background: rgba(15, 23, 42, 0.6);
    border-radius: 12px;
    padding: 1rem;
    display: grid;
    gap: 0.75rem;
    --label-column-width: clamp(8rem, 25vw, 13rem);
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

  .details-grid {
    display: grid;
    gap: 1rem;
  }

  @media (min-width: 768px) {
    .details-grid {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      align-items: start;
    }
  }

  .timings h3 {
    margin: 0;
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
    display: grid;
    grid-template-columns: minmax(6.5rem, var(--label-column-width)) 1fr;
    column-gap: 0.75rem;
    align-items: baseline;
  }

  .data strong {
    color: #94a3b8;
    font-weight: 600;
  }

  .data span {
    display: block;
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

  th {
    color: #94a3b8;
    font-weight: 600;
    padding-right: 1rem;
  }

  td {
    width: auto;
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

  .error-message {
    margin: 0.35rem 0 0;
    color: #fca5a5;
    font-size: 0.9rem;
  }

  .mapped-filters {
    background: rgba(255, 255, 255, 0.04);
    border-radius: 10px;
    padding: 1rem;
    display: grid;
    gap: 0.75rem;
  }

  .mapped-filters.empty {
    color: #cbd5e1;
  }

  .mapped-filters.empty p {
    margin: 0;
  }

  .mapped-filters h3 {
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
    background: rgba(15, 23, 42, 0.4);
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    display: grid;
    gap: 0.25rem;
  }

  .filter-option.selected {
    border: 1px solid #38bdf8;
  }

  .option-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .option-label {
    font-weight: 600;
  }

  .span-hints {
    color: #cbd5e1;
    font-size: 0.9rem;
  }

  .badge {
    background: #0ea5e9;
    color: #0b1224;
    border-radius: 999px;
    padding: 0.15rem 0.5rem;
    font-size: 0.8rem;
  }

  .confidence {
    color: #94a3b8;
    font-size: 0.85rem;
  }

  .mismatches ul {
    margin: 0.25rem 0 0;
    padding-left: 1.25rem;
  }

  .mismatches li {
    margin-bottom: 0.25rem;
    font-size: 0.8rem;
  }

  .issues p {
    margin: 0.25rem 0 0;
    font-size: 0.8rem;
  }
</style>
