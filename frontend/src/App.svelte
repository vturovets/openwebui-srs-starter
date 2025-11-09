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

  const metaEnv = (import.meta as any)?.env ?? {};
  const baseUrl = (globalThis as any).__HOLIDAY_API__ ?? metaEnv?.VITE_API_BASE_URL ?? 'http://localhost:8000';

  let fixtures: Fixtures | null = null;
  let fixtureError = '';
  let loadingFixtures = true;
  let query = '';
  let history: HolidayResultEntry[] = [];
  let mode = 'direct-parse';
  let method: string | null = null;
  let busy = false;
  let downloadAnchor: HTMLAnchorElement | null = null;
  let downloadUrl: string | null = null;

  const CSV_HEADERS = CSV_LOG_FIELDS;

  onMount(async () => {
    try {
      const data = await fetchFixtures(baseUrl);
      fixtures = data;
      mode = data.mode;
      method = data.llmMethod;
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
    const resolvedInput = input || result.transcript || '';
    history = [
      {
        id: generateId(),
        source,
        input: resolvedInput,
        result,
        prompt: buildClarificationPrompt(result),
        timestamp: new Date().toISOString(),
      },
      ...history,
    ];
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
        method: method ?? undefined,
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

  function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  function toRecord(value: unknown): Record<string, unknown> {
    return isRecord(value) ? value : {};
  }

  function toFiniteNumber(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === 'string') {
      const parsed = Number.parseFloat(value);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
    return null;
  }

  function formatTiming(value: unknown): string {
    const numeric = toFiniteNumber(value);
    return numeric === null ? '' : numeric.toFixed(2);
  }

  function formatProbability(value: unknown): string {
    const numeric = toFiniteNumber(value);
    if (numeric !== null) {
      return numeric.toFixed(2);
    }
    if (typeof value === 'string') {
      return value;
    }
    return '';
  }

  function extractLanguageInfo(
    metadata: Record<string, unknown>,
    result: HolidayResult
  ): { code: string; confidence: string } {
    const language = metadata.language;
    let code = '';
    let confidence: unknown;

    if (typeof language === 'string') {
      code = language;
    } else if (isRecord(language)) {
      if (typeof language.code === 'string') {
        code = language.code;
      } else if (typeof language.language === 'string') {
        code = language.language;
      } else if (typeof language.lang === 'string') {
        code = language.lang;
      }
      confidence = language.confidence ?? language.score ?? language.probability;
    }

    if (!code) {
      const dataLanguage = (result.data as Record<string, unknown> | null)?.language;
      if (typeof dataLanguage === 'string') {
        code = dataLanguage;
      }
    }

    return { code, confidence: formatProbability(confidence) };
  }

  function serialiseJson(value: unknown): string {
    if (value === undefined || value === null || value === '') {
      return '';
    }
    return JSON.stringify(value);
  }

  function serialiseTranscript(entry: HolidayResultEntry, metadata: Record<string, unknown>): string {
    const transcript = metadata.transcript;
    if (Array.isArray(transcript)) {
      return JSON.stringify(transcript);
    }
    if (typeof transcript === 'string' && transcript.trim().length > 0) {
      return JSON.stringify([{ role: 'user', text: transcript }]);
    }

    const resultTranscript = (entry.result as VoiceResponse).transcript;
    if (typeof resultTranscript === 'string' && resultTranscript.trim().length > 0) {
      return JSON.stringify([{ role: 'user', text: resultTranscript }]);
    }

    if (entry.input.trim().length > 0) {
      return JSON.stringify([{ role: 'user', text: entry.input }]);
    }

    return '[]';
  }

  function escapeCsv(value: string): string {
    if (/["\n\r,]/.test(value)) {
      return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
  }

  function formatThreshold(value: unknown): string {
    if (typeof value === 'boolean') {
      return value ? 'true' : 'false';
    }
    if (typeof value === 'string') {
      const lowered = value.toLowerCase();
      if (lowered === 'true' || lowered === 'false') {
        return lowered;
      }
    }
    return '';
  }

  function buildOutput(entry: HolidayResultEntry, metadata: Record<string, unknown>): string {
    const output: Record<string, unknown> = {
      status: entry.result.status,
      data: entry.result.data ?? {},
    };

    if (metadata.validation !== undefined) {
      output.validation = metadata.validation;
    }
    if (metadata.error !== undefined) {
      output.error = metadata.error;
    }

    return JSON.stringify(output);
  }

  function resolvePrompt(metadata: Record<string, unknown>, result: HolidayResult): string {
    if (metadata.prompt !== undefined) {
      return serialiseJson(metadata.prompt);
    }
    if (Array.isArray(result.clarifications) && result.clarifications.length) {
      return JSON.stringify(result.clarifications);
    }
    return '';
  }

  function serialiseList(value: unknown): string {
    if (Array.isArray(value)) {
      return JSON.stringify(value);
    }
    return '[]';
  }

  function resolveSessionId(metadata: Record<string, unknown>): string {
    const sessionId = metadata.sessionId ?? metadata.sessionID ?? metadata.session_id;
    return typeof sessionId === 'string' ? sessionId : '';
  }

  function resolvePipelineStatus(result: HolidayResult, metadata: Record<string, unknown>): string {
    if (result.status === 'success') {
      return 'success';
    }
    const rawStatus = typeof metadata.rawStatus === 'string' ? metadata.rawStatus : '';
    if (rawStatus === 'error') {
      return 'error';
    }
    if (result.status === 'clarification' || result.status === 'failed') {
      return 'failed';
    }
    return result.status;
  }

  type CsvRow = Record<string, string | string[]>;

  function buildRow(entry: HolidayResultEntry): CsvRow {
    const metadata = toRecord(entry.result.metadata);
    const timings = toRecord(metadata.timings);
    const llm = toRecord(metadata.llm);
    const languageInfo = extractLanguageInfo(metadata, entry.result);

    const totalTiming =
      toFiniteNumber(timings.totalMs ?? timings.total ?? timings.totalMilliseconds) ?? undefined;

    const pipelineStatus = resolvePipelineStatus(entry.result, metadata);
    const dialogStatus =
      typeof metadata.rawStatus === 'string' ? metadata.rawStatus : entry.result.status;
    const llmProvider =
      typeof llm.provider === 'string'
        ? llm.provider
        : typeof llm.engine === 'string'
          ? llm.engine
          : typeof llm.model === 'string'
            ? llm.model
            : '';

    const row: CsvRow = {
      Timestamp: entry.timestamp,
      'User Input': entry.input,
      'Request Type': entry.source === 'voice' ? 'voice' : 'text',
      'Interaction Mode': typeof metadata.mode === 'string' ? metadata.mode : '',
      'Processing Method': typeof metadata.method === 'string' ? metadata.method : '',
      'Pipeline Status': pipelineStatus,
      'Language Detection': [languageInfo.code, languageInfo.confidence],
      'Processing Time (ms)': formatTiming(totalTiming),
      'LLM Network (ms)': formatTiming(
        timings.llmNetworkMs ?? timings.networkLatencyMs ?? timings.networkMs
      ),
      'LLM Provider': llmProvider,
      'LLM Prompt Id': typeof llm.promptId === 'string' ? llm.promptId : '',
      'LLM Request Id': typeof llm.requestId === 'string' ? llm.requestId : '',
      'LLM Response Id':
        typeof llm.responseId === 'string'
          ? llm.responseId
          : typeof llm.traceId === 'string'
            ? llm.traceId
            : '',
      'Threshold Breached': formatThreshold(timings.thresholdBreached),
      'Missing Fields': serialiseList(metadata.missingFields),
      'Invalid Fields': serialiseList(metadata.invalidFields),
      Transcript: serialiseTranscript(entry, metadata),
      'Prompt JSON': resolvePrompt(metadata, entry.result),
      'Output JSON': buildOutput(entry, metadata),
      'Session Id': resolveSessionId(metadata),
      'Dialog Status': dialogStatus,
    };

    return row;
  }

  function generateCsv(): string {
    const rows = history.map((entry) => buildRow(entry));
    const csvRows = [CSV_HEADERS.map((value) => escapeCsv(value)).join(',')];

    for (const row of rows) {
      const occurrences = new Map<string, number>();
      const values = CSV_HEADERS.map((field) => {
        const count = occurrences.get(field) ?? 0;
        occurrences.set(field, count + 1);

        const value = row[field];
        if (Array.isArray(value)) {
          return escapeCsv(value[count] ?? '');
        }
        if (count === 0) {
          return escapeCsv(value ?? '');
        }
        return '';
      });

      csvRows.push(values.join(','));
    }

    return csvRows.join('\n');
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
        <input
          type="text"
          placeholder="rules"
          bind:value={method}
          data-testid="method-input"
        />
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
        <button type="button" on:click={exportCsv} data-testid="export-button">Export CSV</button>
      </div>
    </form>

    <MicrophoneWidget
      on:voiceResult={handleVoice}
      {handleVoiceUpload}
      mode={mode}
      voiceEnabled={fixtures?.voiceEnabled ?? true}
    />

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

