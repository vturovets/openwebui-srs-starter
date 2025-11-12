<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import MicrophoneWidget from './components/MicrophoneWidget.svelte';
  import StructuredResult from './components/StructuredResult.svelte';
  import { createImportJob, fetchFixtures, parseText, pollImportJob, postVoice } from './lib/api';
  import type {
    Fixtures,
    FixturesConfigurationDefaults,
    FixturesConfigurationFlexibility,
    FixturesPerformanceTargets,
    HolidayResult,
    HolidayResultEntry,
    ImportJobLifecycleStatus,
    ImportJobProgress,
    ImportJobStatusResponse,
    ImportJobValidationError,
    PerformanceSummary,
    UsageSummary,
    VoiceResponse,
  } from './lib/types';
  import { CSV_LOG_FIELDS } from './lib/types';
  import { type PerformanceInference } from './lib/performance';
  import { getExtractedValueRows } from './lib/extractedValues';

  const metaEnv = (import.meta as any)?.env ?? {};
  const baseUrl = (globalThis as any).__HOLIDAY_API__ ?? metaEnv?.VITE_API_BASE_URL ?? 'http://localhost:8000';

  let fixtures: Fixtures | null = null;
  let fixtureError = '';
  let loadingFixtures = true;
  let showFailedOnly = true;
  let query = '';
  let history: HolidayResultEntry[] = [];
  type MethodOption = { id: string; label: string };

  let mode = 'direct-parse';
  let dialogOverrideAllowed = false;
  let method = '';
  let methodOptions: MethodOption[] = [];
  let busy = false;
  let downloadAnchor: HTMLAnchorElement | null = null;
  let downloadUrl: string | null = null;
  let importInput: HTMLInputElement | null = null;

  const CSV_HEADERS = CSV_LOG_FIELDS;
  const SUCCESS_STATUSES = new Set(['success', 'ok', 'passed']);

  type ImportPerformanceTargets = {
    thresholdMs: number;
    sampleSize: number;
    significance: number;
  };

  const DEFAULT_IMPORT_PERFORMANCE_TARGETS: ImportPerformanceTargets = {
    thresholdMs: 1000,
    sampleSize: 1000,
    significance: 0.95,
  };

  let importPerformanceTargets: ImportPerformanceTargets = {
    ...DEFAULT_IMPORT_PERFORMANCE_TARGETS,
  };

  let importPerformanceSummary: PerformanceSummary | null = null;
  let importUsageSummary: UsageSummary | null = null;
  type ImportJobUiStatus = ImportJobLifecycleStatus | 'idle' | 'uploading';
  let importBusy = false;
  let importJobStatus: ImportJobUiStatus = 'idle';
  let importJobMessage = '';
  let importJobError = '';
  let importJobProgress: ImportJobProgress | null = null;
  let importJobValidationErrors: ImportJobValidationError[] = [];
  let importJobController: AbortController | null = null;
  const ACTIVE_IMPORT_STATUSES = new Set<ImportJobLifecycleStatus>([
    'pending',
    'queued',
    'processing',
  ]);
  const FAILURE_IMPORT_STATUSES = new Set<ImportJobLifecycleStatus>(['failed', 'cancelled']);

  function resetImportJobState() {
    importBusy = false;
    importJobStatus = 'idle';
    importJobMessage = '';
    importJobError = '';
    importJobProgress = null;
    importJobValidationErrors = [];
  }

  function stopImportPolling() {
    if (importJobController) {
      importJobController.abort();
      importJobController = null;
    }
  }

  function applyImportStatus(status: ImportJobStatusResponse) {
    importJobStatus = status.status;
    importJobMessage = status.message ?? '';
    importJobProgress = status.progress ?? null;
    importJobValidationErrors = status.validationErrors ?? [];
    if (ACTIVE_IMPORT_STATUSES.has(status.status)) {
      importBusy = true;
      importJobError = '';
    }
  }

  function handleFinalImportStatus(status: ImportJobStatusResponse) {
    importJobController = null;
    applyImportStatus(status);
    if (status.status === 'completed') {
      importPerformanceSummary = status.performanceSummary ?? null;
      importUsageSummary = status.usageSummary ?? null;
      importBusy = false;
      importJobError = '';
    } else if (FAILURE_IMPORT_STATUSES.has(status.status)) {
      importPerformanceSummary = null;
      importUsageSummary = null;
      importBusy = false;
      importJobError = status.message || status.errorCode || 'Import job failed';
    } else {
      importBusy = false;
    }
  }

  function startImportPolling(jobId: string) {
    stopImportPolling();
    const controller = new AbortController();
    importJobController = controller;
    importBusy = true;
    pollImportJob(baseUrl, jobId, {
      signal: controller.signal,
      onUpdate: (status) => {
        if (controller.signal.aborted) {
          return;
        }
        applyImportStatus(status);
      },
    })
      .then((finalStatus) => {
        if (controller.signal.aborted) {
          return;
        }
        handleFinalImportStatus(finalStatus);
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return;
        }
        importBusy = false;
        importJobController = null;
        importJobStatus = 'failed';
        importJobError =
          error instanceof Error ? error.message : 'Import job failed';
      });
  }

  function toFiniteNumber(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) {
        return null;
      }
      const parsed = Number(trimmed);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
    return null;
  }

  function sanitiseImportPerformanceTargets(
    targets: FixturesPerformanceTargets | undefined
  ): ImportPerformanceTargets {
    const resolved: ImportPerformanceTargets = { ...DEFAULT_IMPORT_PERFORMANCE_TARGETS };

    if (!targets) {
      return resolved;
    }

    const threshold = toFiniteNumber(targets.importP95ThresholdMs);
    if (threshold !== null) {
      resolved.thresholdMs = Math.max(0, threshold);
    }

    const sampleSize = toFiniteNumber(targets.importP95SampleSize);
    if (sampleSize !== null) {
      resolved.sampleSize = Math.max(0, Math.floor(sampleSize));
    }

    const significance = toFiniteNumber(targets.importP95Significance);
    if (significance !== null && significance > 0 && significance <= 1) {
      resolved.significance = significance;
    }

    return resolved;
  }

  const INFERENCE_LABELS: Record<PerformanceInference, string> = {
    'meets-target': 'Meets target',
    'violates-target': 'Violates target',
    inconclusive: 'Inconclusive',
  };

  function formatInference(summary: PerformanceSummary | null): string {
    if (!summary) {
      return '—';
    }
    if (summary.inference) {
      return INFERENCE_LABELS[summary.inference];
    }
    if (summary.sampleSize > 0 && summary.requestCount < summary.sampleSize) {
      return 'Insufficient data';
    }
    return 'Unavailable';
  }

  function formatMetric(value: number, decimals = 2): string {
    if (!Number.isFinite(value)) {
      return value.toString();
    }
    return Number(value.toFixed(decimals)).toString();
  }

  function formatUsageValue(value: number | undefined, decimals = 2): string {
    if (typeof value !== 'number') {
      return '—';
    }
    return formatMetric(value, decimals);
  }

  function formatUsageValueWithUnit(
    value: number | undefined,
    unit: string,
    decimals = 2
  ): string {
    if (typeof value !== 'number') {
      return '—';
    }
    return `${formatMetric(value, decimals)} ${unit}`;
  }

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

  function isDialogMode(value: unknown): boolean {
    return typeof value === 'string' && value.trim().toLowerCase() === 'dialog';
  }

  onMount(async () => {
    try {
      const data = await fetchFixtures(baseUrl);
      fixtures = data;
      importPerformanceTargets = sanitiseImportPerformanceTargets(data.performanceTargets);
      showFailedOnly = typeof data.showFailedOnly === 'boolean' ? data.showFailedOnly : true;
      mode = data.mode;
      dialogOverrideAllowed = isDialogMode(data.mode);
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

  onDestroy(() => {
    stopImportPolling();
    if (downloadUrl) {
      URL.revokeObjectURL(downloadUrl);
      downloadUrl = null;
    }
  });

  $: if (!dialogOverrideAllowed && mode !== 'direct-parse') {
    mode = 'direct-parse';
  }

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

  function isFailureStatus(status: unknown): boolean {
    if (typeof status !== 'string') {
      return true;
    }

    const normalized = status.trim().toLowerCase();
    if (!normalized) {
      return true;
    }

    return !SUCCESS_STATUSES.has(normalized);
  }

  function shouldDisplayImportedEntry(entry: HolidayResultEntry): boolean {
    if (!showFailedOnly) {
      return true;
    }

    return isFailureStatus(entry?.result?.status);
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
    stopImportPolling();
    resetImportJobState();
    importPerformanceSummary = null;
    importUsageSummary = null;
    importJobStatus = 'uploading';
    importJobMessage = 'Uploading CSV…';
    importJobError = '';
    importJobProgress = null;
    importJobValidationErrors = [];
    importBusy = true;

    try {
      const submission = await createImportJob(baseUrl, file);
      importJobStatus = submission.status;
      importJobMessage = submission.message ?? '';
      if (FAILURE_IMPORT_STATUSES.has(submission.status)) {
        importBusy = false;
        importJobError = submission.message || 'Import job failed';
        return;
      }
      startImportPolling(submission.id);
    } catch (error) {
      importBusy = false;
      importJobStatus = 'failed';
      importJobError =
        error instanceof Error ? error.message : 'Unable to submit import job';
    } finally {
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
    if (!history.length && !importPerformanceSummary && !importUsageSummary) {
      return;
    }

    history = [];
    importPerformanceSummary = null;
    importUsageSummary = null;
    stopImportPolling();
    resetImportJobState();

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

      {#if dialogOverrideAllowed}
        <label>
          Interaction mode
          <select bind:value={mode} data-testid="mode-select">
            <option value="direct-parse">Direct parse</option>
            <option value="dialog">Dialog</option>
          </select>
        </label>
      {/if}

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
          disabled={busy || importBusy}
          data-testid="import-button"
        >
          Import CSV
        </button>
        <button type="button" on:click={exportCsv} data-testid="export-button">Export CSV</button>
      </div>

      {#if importJobStatus === 'uploading'}
        <p class="info" data-testid="import-status">Uploading CSV…</p>
      {:else if importJobStatus === 'pending' || importJobStatus === 'queued'}
        <p class="info" data-testid="import-status">
          Import job queued
          {#if importJobProgress}
            <span data-testid="import-progress">
              {importJobProgress.processed}
              {#if importJobProgress.total !== null}
                / {importJobProgress.total}
              {/if}
            </span>
          {/if}
          {#if importJobMessage}
            — {importJobMessage}
          {/if}
        </p>
      {:else if importJobStatus === 'processing'}
        <p class="info" data-testid="import-status">
          Import in progress
          {#if importJobProgress}
            <span data-testid="import-progress">
              {importJobProgress.processed}
              {#if importJobProgress.total !== null}
                / {importJobProgress.total}
              {/if}
            </span>
          {/if}
          {#if importJobMessage}
            — {importJobMessage}
          {/if}
        </p>
      {:else if importJobStatus === 'completed' && importJobMessage}
        <p class="info" data-testid="import-status">{importJobMessage}</p>
      {/if}

      {#if importJobStatus === 'failed' || importJobStatus === 'cancelled'}
        <div class="import-errors">
          <p class="error" data-testid="import-error">{importJobError || importJobMessage || 'Import failed'}</p>
          {#if importJobValidationErrors.length}
            <ul class="error-details" data-testid="import-validation-errors">
              {#each importJobValidationErrors as validation, index (validation.message + index)}
                <li>
                  {#if typeof validation.row === 'number' && validation.row > 0}
                    Row {validation.row}: 
                  {/if}
                  {validation.message}
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}
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
        disabled={(history.length === 0 && !importPerformanceSummary && !importUsageSummary) || importBusy}
        data-testid="reset-button"
      >
        Reset
      </button>
    </div>

  </section>

  <div class="content">
    {#if importPerformanceSummary || importUsageSummary}
      <div class="summary-row">
        <section class="summary-card performance-summary" data-testid="performance-summary">
          <h2>Performance summary</h2>
          <dl>
            <div class="metric-row">
              <dt>Requests processed</dt>
              <dd data-testid="performance-requests">
                {#if importPerformanceSummary}
                  {importPerformanceSummary.requestCount}
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>Mean response time</dt>
              <dd data-testid="performance-mean">
                {#if importPerformanceSummary}
                  {formatMetric(importPerformanceSummary.meanResponseMs)} ms
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>P95 response time</dt>
              <dd data-testid="performance-p95">
                {#if importPerformanceSummary}
                  {#if importPerformanceSummary.p95ResponseMs !== null}
                    {formatMetric(importPerformanceSummary.p95ResponseMs)} ms
                  {:else}
                    —
                  {/if}
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>Threshold</dt>
              <dd data-testid="performance-threshold">
                {#if importPerformanceSummary}
                  {formatMetric(importPerformanceSummary.thresholdMs)} ms
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>Inference</dt>
              <dd data-testid="performance-inference">
                {#if importPerformanceSummary}
                  {formatInference(importPerformanceSummary)}
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>Accuracy</dt>
              <dd data-testid="performance-accuracy">
                {#if importPerformanceSummary}
                  {formatMetric(importPerformanceSummary.accuracy)}%
                {:else}
                  —
                {/if}
              </dd>
            </div>
          </dl>
        </section>

        <section class="summary-card usage-summary" data-testid="usage-summary">
          <h2>Usage footprint summary</h2>
          <dl>
            <div class="metric-row">
              <dt>Total tokens in</dt>
              <dd data-testid="usage-tokens-in">{formatUsageValue(importUsageSummary?.tokensIn, 0)}</dd>
            </div>
            <div class="metric-row">
              <dt>Total tokens out</dt>
              <dd data-testid="usage-tokens-out">{formatUsageValue(importUsageSummary?.tokensOut, 0)}</dd>
            </div>
            <div class="metric-row">
              <dt>API calls</dt>
              <dd data-testid="usage-api-calls">{formatUsageValue(importUsageSummary?.apiCalls, 0)}</dd>
            </div>
            <div class="metric-row">
              <dt>CPU time</dt>
              <dd data-testid="usage-cpu">{formatUsageValueWithUnit(importUsageSummary?.cpuMs, 'ms')}</dd>
            </div>
            <div class="metric-row">
              <dt>RAM footprint</dt>
              <dd data-testid="usage-ram">{formatUsageValueWithUnit(importUsageSummary?.ramMbSeconds, 'MB·s')}</dd>
            </div>
          </dl>
        </section>
      </div>
    {/if}

    <section class="results" aria-live="polite">
      {#if !history.length}
        <p data-testid="empty-state">Run a parse to see structured output.</p>
      {:else}
        {#each history as entry (entry.id)}
          <StructuredResult {entry} />
        {/each}
      {/if}
    </section>
  </div>

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
  <a
    bind:this={downloadAnchor}
    class="visually-hidden"
    aria-hidden="true"
    tabindex="-1"
    href={downloadUrl ?? '#'}
  >
    Download CSV
  </a>
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
    position: sticky;
    top: 1.5rem;
    align-self: start;
    max-height: calc(100vh - 3rem);
    overflow-y: auto;
  }

  .panel h1 {
    margin: 0 0 0.5rem;
    font-size: 1.5rem;
  }

  .content {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    position: relative;
  }

  .summary-row {
    position: sticky;
    top: 1.5rem;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1.5rem;
    align-self: stretch;
    z-index: 2;
    padding-block: 0.5rem;
    isolation: isolate;
  }

  .summary-row::before {
    content: '';
    position: absolute;
    inset: 0;
    background: #0f172a;
    border-radius: 18px;
    z-index: -1;
    pointer-events: none;
  }

  .summary-card {
    background: #1e293b;
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 16px;
    padding: 2rem 2.25rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.5rem;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.4);
  }

  .summary-card h2 {
    margin: 0;
    font-size: 1.75rem;
    text-align: center;
    letter-spacing: 0.02em;
  }

  .summary-card dl {
    margin: 0;
    width: 100%;
    display: grid;
    gap: 1rem;
  }

  .summary-card .metric-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.75rem;
    align-items: baseline;
  }

  .summary-card dt {
    font-size: 0.85rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #94a3b8;
    text-align: left;
  }

  .summary-card dd {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 600;
    text-align: right;
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
    padding-top: 0.25rem;
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

    .panel {
      position: static;
      max-height: none;
      overflow: visible;
    }

    .summary-row {
      position: relative;
      grid-template-columns: 1fr;
      gap: 1rem;
    }

    .summary-row::before {
      border-radius: 0;
    }
  }
</style>

