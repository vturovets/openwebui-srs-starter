<script lang="ts">
  import { onMount } from 'svelte';
  import MicrophoneWidget from './components/MicrophoneWidget.svelte';
  import StructuredResult from './components/StructuredResult.svelte';
  import { fetchFixtures, parseText, postVoice } from './lib/api';
  import type { HolidayResult, HolidayResultEntry, Fixtures } from './lib/types';

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
  let csvPreview = '';

  onMount(async () => {
    try {
      const data = await fetchFixtures(baseUrl);
      fixtures = data;
      mode = data.mode ?? mode;
      method = data.llmMethod ?? null;
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

  function trackEntry(source: 'text' | 'voice', result: HolidayResult, input: string) {
    history = [
      {
        id: generateId(),
        source,
        input,
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

  async function handleVoice(event: CustomEvent<{ transcript: string; response: HolidayResult }>) {
    const { transcript, response } = event.detail;
    trackEntry('voice', response, transcript);
  }

  async function handleVoiceUpload(formData: FormData) {
    return postVoice(baseUrl, formData);
  }

  function formatRecognizedForCsv(value: unknown): string {
    if (Array.isArray(value)) {
      return value
        .map((item) => formatRecognizedForCsv(item))
        .filter((item) => item.length > 0)
        .join(' | ');
    }

    if (value === null) {
      return 'null';
    }
    if (value === undefined) {
      return '';
    }
    if (typeof value === 'number' && Number.isFinite(value)) {
      return Number(value.toFixed(3)).toString();
    }
    if (typeof value === 'string') {
      return value;
    }
    return JSON.stringify(value);
  }

  function generateCsv(): string {
    const header = [
      'Timestamp',
      'Source',
      'Status',
      'Input',
      'Mode',
      'Method',
      'TotalMs',
      'Airports',
      'Destinations',
      'Dates',
    ];
    const rows = history.map((entry) => {
      const timings = entry.result.metadata?.timings ?? {};
      const recognized = entry.result.metadata?.recognizedSummaries ?? {};
      return [
        entry.timestamp,
        entry.source,
        entry.result.status,
        entry.input.replace(/\n/g, ' '),
        entry.result.metadata?.mode ?? '',
        entry.result.metadata?.method ?? '',
        timings.totalMs ?? '',
        formatRecognizedForCsv(recognized.airports),
        formatRecognizedForCsv(recognized.destinations),
        formatRecognizedForCsv(recognized.dates),
      ].join(',');
    });
    return [header.join(','), ...rows].join('\n');
  }

  function previewCsv() {
    csvPreview = generateCsv();
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
            <strong>Voice Enabled:</strong>
            <span>{fixtures.voiceEnabled ? 'Yes' : 'No'}</span>
          </div>
        </div>
      {/if}
    </header>

    <form class="query" on:submit|preventDefault={handleSubmit} data-testid="parse-form">
      <label>
        Interaction mode
        <select bind:value={mode} data-testid="mode-select">
          <option value="direct-parse">Direct parse</option>
          <option value="dialog">Dialog</option>
        </select>
      </label>

      <label>
        Method
        <input
          type="text"
          placeholder="rules"
          bind:value={method}
          data-testid="method-input"
        />
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
        <button type="button" on:click={previewCsv} data-testid="export-button">Export CSV</button>
      </div>
    </form>

    <MicrophoneWidget
      on:voiceResult={handleVoice}
      {handleVoiceUpload}
      mode={mode}
      voiceEnabled={fixtures?.voiceEnabled ?? true}
    />

    {#if csvPreview}
      <section class="csv" data-testid="csv-preview">
        <h2>CSV Preview</h2>
        <pre>{csvPreview}</pre>
      </section>
    {/if}
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

  .csv {
    background: rgba(15, 23, 42, 0.6);
    padding: 0.75rem;
    border-radius: 8px;
    font-size: 0.8rem;
    max-height: 160px;
    overflow: auto;
  }

  @media (max-width: 900px) {
    .app {
      grid-template-columns: 1fr;
    }
  }
</style>

