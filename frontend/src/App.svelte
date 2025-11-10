<script lang="ts">
  import { onMount } from 'svelte';
  import MicrophoneWidget from './components/MicrophoneWidget.svelte';
  import StructuredResult from './components/StructuredResult.svelte';
  import { fetchFixtures, parseText, postVoice } from './lib/api';
  import type {
    Fixtures,
    FixturesConfigurationDefaults,
    FixturesConfigurationFlexibility,
    HolidayResult,
    HolidayResultEntry,
    VoiceResponse,
  } from './lib/types';
  import { CSV_LOG_FIELDS } from './lib/types';
  import { getExtractedValueRows } from './lib/extractedValues';
  import { parseCsv } from './lib/csv';
  import { compareExpectedValues, parseExpectedValues } from './lib/importUtils';

  const metaEnv = (import.meta as any)?.env ?? {};
  const baseUrl = (globalThis as any).__HOLIDAY_API__ ?? metaEnv?.VITE_API_BASE_URL ?? 'http://localhost:8000';

  let fixtures: Fixtures | null = null;
  let fixtureError = '';
  let loadingFixtures = true;
  let query = '';
  let history: HolidayResultEntry[] = [];
  type MethodOption = { id: string; label: string };

  let mode = 'direct-parse';
  let method = '';
  let methodOptions: MethodOption[] = [];
  let busy = false;
  let downloadAnchor: HTMLAnchorElement | null = null;
  let downloadUrl: string | null = null;
  let importInput: HTMLInputElement | null = null;

  const CSV_HEADERS = CSV_LOG_FIELDS;

  function normaliseMethodOptions(value: unknown): MethodOption[] {
    if (!Array.isArray(value)) {
      return [];
    }

    const options: MethodOption[] = [];
    const seen = new Set<string>();

    for (const entry of value) {
      if (typeof entry === 'string') {
        const id = entry.trim();
        if (id.length > 0 && !seen.has(id)) {
          options.push({ id, label: id });
          seen.add(id);
        }
        continue;
      }

      if (!entry || typeof entry !== 'object') {
        continue;
      }

      const record = entry as Record<string, unknown>;
      const rawId = record.id;
      if (typeof rawId !== 'string') {
        continue;
      }
      const id = rawId.trim();
      if (!id || seen.has(id)) {
        continue;
      }

      const rawLabel = record.label;
      const label = typeof rawLabel === 'string' && rawLabel.trim().length > 0 ? rawLabel.trim() : id;

      options.push({ id, label });
      seen.add(id);
    }

    return options;
  }

  onMount(async () => {
    try {
      const data = await fetchFixtures(baseUrl);
      fixtures = data;
      mode = data.mode;
      methodOptions = normaliseMethodOptions(data?.availableMethods);
      method = typeof data.llmMethod === 'string' ? data.llmMethod : '';
      if (method && !methodOptions.some((option) => option.id === method)) {
        methodOptions = [...methodOptions, { id: method, label: method }];
      }
    } catch (error) {
      fixtureError = error instanceof Error ? error.message : 'Unable to load fixtures';
    } finally {
      loadingFixtures = false;
    }
  });

  function buildClarificationPrompt(result: HolidayResult): string {
    const clarifications = result.clarifications ?? [];
    if (!clarifications.length) {
      return '';
    }
    const prompt = clarifications
      .map((item) => `${item.parameter}: ${item.message}`)
      .join('\n');
    return prompt;
  }

  function generateId(): string {
    const cryptoObj = (globalThis as any).crypto;
    if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
      return cryptoObj.randomUUID();
    }
    return `entry-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function createEntry(
    source: 'text' | 'voice',
    result: HolidayResult,
    input: string
  ): HolidayResultEntry {
    const resolvedInput = input || result.transcript || '';
    return {
      id: generateId(),
      source,
      input: resolvedInput,
      result,
      prompt: buildClarificationPrompt(result),
      timestamp: new Date().toISOString(),
    };
  }

  function addEntry(entry: HolidayResultEntry) {
    history = [entry, ...history];
  }

  function formatDefaultParticipants(defaults?: FixturesConfigurationDefaults): string {
    if (!defaults) {
      return '—';
    }

    const participants: string[] = [];
    const { adults, nonAdults } = defaults;

    if (typeof adults === 'number' && Number.isFinite(adults)) {
      participants.push(`${adults} adult${adults === 1 ? '' : 's'}`);
    }

    if (typeof nonAdults === 'number' && Number.isFinite(nonAdults)) {
      participants.push(`${nonAdults} non-adult${nonAdults === 1 ? '' : 's'}`);
    }

    return participants.length ? participants.join(' / ') : '—';
  }

  function resolveDefaultFlexibility(flexibility?: FixturesConfigurationFlexibility): string {
    const options = flexibility?.flexibleList ?? [];
    const defaultOption = options.find((option) => option?.isDefault);

    if (!defaultOption) {
      return '—';
    }

    const id = defaultOption.id;
    if (typeof id === 'string' && id.trim().length > 0) {
      const numericId = Number(id);
      if (Number.isFinite(numericId)) {
        return `${numericId}`;
      }
      return id.trim();
    }

    const name = defaultOption.name;
    if (typeof name === 'string' && name.trim().length > 0) {
      const match = name.match(/\d+/);
      if (match) {
        return match[0];
      }
      return name.trim();
    }

    return '—';
  }

  function trackEntry(
    source: 'text' | 'voice',
    result: HolidayResult,
    input: string
  ) {
    addEntry(createEntry(source, result, input));
  }

  async function handleSubmit(event: Event) {
    event.preventDefault();
    if (!query.trim()) {
      return;
    }
    busy = true;
    try {
      const payload = await parseText(baseUrl, query, {
        mode,
        method: method || undefined,
      });
      trackEntry('text', payload, query);
      query = '';
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to parse request';
      trackEntry('text', {
        status: 'error',
        data: {},
        metadata: { message },
        clarifications: [],
      }, query);
    } finally {
      busy = false;
    }
  }

  async function handleVoice(event: CustomEvent<{ transcript: string; response: VoiceResponse }>) {
    const { transcript, response } = event.detail;
    trackEntry('voice', response, transcript);
  }

  async function handleVoiceUpload(formData: FormData) {
    return postVoice(baseUrl, formData);
  }

  function triggerImport() {
    if (importInput) {
      importInput.click();
    }
  }

  async function handleImportChange(event: Event) {
    const target = event.currentTarget as HTMLInputElement | null;
    if (!target?.files || target.files.length === 0) {
      return;
    }

    const [file] = target.files;
    busy = true;
    try {
      const text = await file.text();
      const records = parseCsv(text);

      for (const record of records) {
        const userInput = (record['User input'] ?? '').trim();
        if (!userInput) {
          continue;
        }

        const expectedRaw = record['Expected values'] ?? '';
        const expectedValues = parseExpectedValues(expectedRaw);

        try {
          const payload = await parseText(baseUrl, userInput, {
            mode,
            method: method || undefined,
          });

          let entry = createEntry('text', payload, userInput);

          if (expectedValues.length) {
            const actualRows = getExtractedValueRows(entry);
            const mismatches = compareExpectedValues(actualRows, expectedValues);

            if (mismatches.length) {
              const updatedResult: HolidayResult = {
                ...payload,
                status: 'failed',
                metadata: {
                  ...payload.metadata,
                  expectedValueMismatches: mismatches,
                },
              };

              entry = {
                ...entry,
                result: updatedResult,
                prompt: buildClarificationPrompt(updatedResult),
              };
            }
          }

          addEntry(entry);
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Unable to parse request';
          const failureResult: HolidayResult = {
            status: 'error',
            data: {},
            metadata: { message },
            clarifications: [],
          };
          addEntry(createEntry('text', failureResult, userInput));
        }
      }
    } finally {
      busy = false;
      target.value = '';
    }
  }


  function escapeCsv(value: string): string {
    if (/[",\n\r]/.test(value)) {
      return '"' + value.replace(/"/g, '""') + '"';
    }
    return value;
  }

  type CsvRow = Record<string, string>;

  function buildRow(entry: HolidayResultEntry): CsvRow {
    const extractedRows = getExtractedValueRows(entry);
    const extractedValues = extractedRows.length
      ? extractedRows.map(({ label, value }) => `${label}: ${value}`).join(' | ')
      : '';

    return {
      'User input': entry.input,
      'Extracted values': extractedValues,
    };
  }

  function generateCsv(): string {
    const header = CSV_HEADERS.map((value) => escapeCsv(value)).join(',');
    const data = history.map((entry) => {
      const row = buildRow(entry);
      return CSV_HEADERS.map((field) => escapeCsv(row[field] ?? '')).join(',');
    });

    return [header, ...data].join('\n');
  }

  function exportCsv() {
    if (!history.length) {
      return;
    }

    const csvContent = generateCsv();

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);

    if (downloadUrl) {
      URL.revokeObjectURL(downloadUrl);
    }
    downloadUrl = url;

    const filename = `holiday-search-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
    if (downloadAnchor) {
      downloadAnchor.href = url;
      downloadAnchor.download = filename;
      downloadAnchor.click();
    }

    setTimeout(() => {
      if (downloadUrl === url) {
        URL.revokeObjectURL(url);
        downloadUrl = null;
      } else {
        URL.revokeObjectURL(url);
      }
    }, 0);
  }

  function resetHistory() {
    if (!history.length) {
      return;
    }

    history = [];

    if (downloadUrl) {
      URL.revokeObjectURL(downloadUrl);
      downloadUrl = null;
    }
  }
</script>

<main class="app">
  <section class="panel">
    <header>
      <h1>Holiday Search Console</h1>
      {#if loadingFixtures}
        <p data-testid="fixtures-loading">Loading fixtures…</p>
      {:else if fixtureError}
        <p class="error" data-testid="fixtures-error">{fixtureError}</p>
      {:else if fixtures}
        <div class="fixtures" data-testid="fixtures-loaded">
          <div>
            <strong>Default Participants:</strong>
            <span>{formatDefaultParticipants(fixtures.configuration?.defaults)}</span>
          </div>
          <div>
            <strong>Flexibility, days:</strong>
            <span>{resolveDefaultFlexibility(fixtures.configuration?.flexibility)}</span>
          </div>
          <div>
            <strong>Airports:</strong>
            <span>{fixtures.airports.join(', ') || '—'}</span>
          </div>
          <div>
            <strong>Destinations:</strong>
            <span>{fixtures.destinations.join(', ') || '—'}</span>
          </div>
        </div>
      {/if}
    </header>

    <form class="query" on:submit|preventDefault={handleSubmit} data-testid="parse-form">
      <label>
        Method
        <select
          bind:value={method}
          disabled={!methodOptions.length}
          data-testid="method-select"
        >
          {#if !methodOptions.length}
            <option value="">No methods available</option>
          {:else}
            {#each methodOptions as option}
              <option value={option.id}>{option.id}</option>
            {/each}
          {/if}
        </select>
      </label>

      <label>
        Interaction mode
        <select bind:value={mode} data-testid="mode-select">
          <option value="direct-parse">Direct parse</option>
          <option value="dialog">Dialog</option>
        </select>
      </label>

      <label class="full-width">
        Ask for a holiday
        <textarea
          bind:value={query}
          rows="3"
          placeholder="Find me a trip from Amsterdam to Italy next October"
          data-testid="query-input"
        ></textarea>
      </label>

      <div class="actions">
        <button type="submit" disabled={busy} data-testid="submit-button">{busy ? 'Parsing…' : 'Parse request'}</button>
        <button
          type="button"
          on:click={triggerImport}
          disabled={busy}
          data-testid="import-button"
        >
          Import CSV
        </button>
        <button type="button" on:click={exportCsv} data-testid="export-button">Export CSV</button>
      </div>
    </form>

    <MicrophoneWidget
      on:voiceResult={handleVoice}
      {handleVoiceUpload}
      mode={mode}
      voiceEnabled={fixtures?.voiceEnabled ?? true}
    />

    <div class="reset-actions">
      <button
        type="button"
        class="reset-button"
        on:click={resetHistory}
        disabled={!history.length}
        data-testid="reset-button"
      >
        Reset
      </button>
    </div>

  </section>

  <section class="results" aria-live="polite">
    {#if !history.length}
      <p data-testid="empty-state">Run a parse to see structured output.</p>
    {:else}
      {#each history as entry (entry.id)}
        <StructuredResult {entry} />
      {/each}
    {/if}
  </section>

  <input
    bind:this={importInput}
    class="visually-hidden"
    type="file"
    accept=".csv,text/csv"
    on:change={handleImportChange}
    aria-hidden="true"
    data-testid="import-input"
    tabindex="-1"
  />
  <a bind:this={downloadAnchor} class="visually-hidden" aria-hidden="true" tabindex="-1"></a>
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: system-ui, sans-serif;
    background: #0f172a;
    color: #e2e8f0;
  }

  .app {
    display: grid;
    grid-template-columns: 360px 1fr;
    gap: 1.5rem;
    min-height: 100vh;
    padding: 1.5rem;
    box-sizing: border-box;
    align-items: start;
  }

  .panel {
    background: #1e293b;
    border-radius: 12px;
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .panel h1 {
    margin: 0 0 0.5rem;
    font-size: 1.5rem;
  }

  .fixtures {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.9rem;
  }

  .query {
    display: grid;
    gap: 0.75rem;
  }

  label {
    display: grid;
    gap: 0.25rem;
    font-size: 0.85rem;
  }

  textarea,
  input,
  select,
  button {
    font: inherit;
  }

  input,
  select,
  textarea {
    padding: 0.5rem;
    border-radius: 8px;
    border: 1px solid #334155;
    background: #0f172a;
    color: inherit;
  }

  textarea:focus,
  input:focus,
  select:focus {
    outline: 2px solid #38bdf8;
    outline-offset: 1px;
  }

  .actions {
    display: flex;
    gap: 0.5rem;
  }

  button {
    padding: 0.6rem 1rem;
    border-radius: 999px;
    border: none;
    background: #38bdf8;
    color: #0f172a;
    cursor: pointer;
    transition: background 0.2s;
  }

  button[disabled] {
    opacity: 0.5;
    cursor: not-allowed;
  }

  button:hover:enabled {
    background: #0ea5e9;
  }

  .reset-actions {
    margin-top: auto;
  }

  .reset-button {
    background: transparent;
    color: #38bdf8;
    border: 1px solid #38bdf8;
    padding-inline: 1.25rem;
  }

  .reset-button:hover:enabled {
    background: rgba(56, 189, 248, 0.1);
  }

  .results {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .error {
    color: #fca5a5;
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  @media (max-width: 900px) {
    .app {
      grid-template-columns: 1fr;
    }
  }
</style>

