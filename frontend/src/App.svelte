<script lang="ts">
  import { onMount } from 'svelte';
  import MicrophoneWidget from './components/MicrophoneWidget.svelte';
  import StructuredResult from './components/StructuredResult.svelte';
  import { fetchFixtures, parseText, postVoice, summarizeImport } from './lib/api';
  import type {
    Fixtures,
    FixturesConfigurationDefaults,
    FixturesConfigurationFlexibility,
    HolidayResult,
    HolidayResultEntry,
    ImportOperationPayload,
    ImportSummaryRequest,
    ImportSummaryResponse,
    UsageSummary as ImportUsageSummary,
    VoiceResponse,
    ShowResults,
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
  let showResults: ShowResults = 'SHOW_ALL';
  let query = '';
  let history: HolidayResultEntry[] = [];
  type MethodOption = { id: string; label: string };

  type InterpretationMode = 'holiday' | 'preferences';

  let mode = 'direct-parse';
  let interpretationMode: InterpretationMode = 'holiday';
  let parseMode = mode;
  let isPreferencesMode = false;
  let dialogOverrideAllowed = false;
  let method = '';
  let methodOptions: MethodOption[] = [];
  let busy = false;
  let downloadAnchor: HTMLAnchorElement | null = null;
  let downloadUrl: string | null = null;
  let importInput: HTMLInputElement | null = null;
  let resettingHistory = false;
  let latestStatus: string | null = null;

  const CSV_HEADERS = CSV_LOG_FIELDS;
  const SUCCESS_STATUSES = new Set(['success', 'ok', 'passed']);
  const SHOW_RESULTS_VALUES: ShowResults[] = ['SHOW_FAILED_ONLY', 'SUPPRESS', 'SHOW_ALL'];

  type PerformanceSummary = ImportSummaryResponse['performance'];
  type UsageSummary = ImportUsageSummary;
  type SummaryRow = { label: string; value: string };

  let importPerformanceSummary: PerformanceSummary | null = null;
  let importUsageSummary: UsageSummary | null = null;
  let importMethod: string | null = null;
  let importProgress: { processed: number; total: number } | null = null;

  function formatMetric(value: number | null | undefined, decimals = 2): string {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return '—';
    }
    return Number(value.toFixed(decimals)).toString();
  }

  function formatConfidence(confidenceLevel: number | null | undefined): string {
    if (typeof confidenceLevel !== 'number' || !Number.isFinite(confidenceLevel)) {
      return '';
    }
    return ` (${formatMetric(confidenceLevel * 100, 0)}% CI)`;
  }

  function formatP95Inference(summary: PerformanceSummary | null): string {
    if (!summary) {
      return '—';
    }
    const inference = summary.p95.inference;
    if (inference === 'insufficient-data') {
      return 'Insufficient data';
    }
    const label = inference === 'meet-target' ? 'Meets target' : 'Above target';
    return `${label}${formatConfidence(summary.p95.confidenceLevel)}`;
  }

  function formatAccuracyInference(summary: PerformanceSummary | null): string {
    if (!summary) {
      return '—';
    }
    const inference = summary.accuracy.inference;
    if (inference === 'insufficient-data') {
      return 'Insufficient data';
    }
    const label = inference === 'meet-target' ? 'Meets target' : 'Below target';
    return `${label}${formatConfidence(summary.accuracy.confidenceLevel)}`;
  }

  function formatUsageValue(value: number | null | undefined, decimals = 2): string {
    if (typeof value !== 'number') {
      return '—';
    }
    return formatMetric(value, decimals);
  }

  function formatUsageValueWithUnit(
    value: number | null | undefined,
    unit: string,
    decimals = 2
  ): string {
    if (typeof value !== 'number') {
      return '—';
    }
    return `${formatMetric(value, decimals)} ${unit}`;
  }

  function buildPerformanceSummaryRows(summary: PerformanceSummary | null): SummaryRow[] {
    return [
      { label: 'Method', value: summary?.method ?? '—' },
      {
        label: 'Requests processed',
        value: summary ? summary.requestCount.toString() : '—',
      },
      {
        label: 'Mean response time',
        value: summary ? `${formatMetric(summary.meanResponseMs)} ms` : '—',
      },
      {
        label: 'P95 response time',
        value:
          summary && summary.p95.valueMs !== null ? `${formatMetric(summary.p95.valueMs)} ms` : '—',
      },
      {
        label: 'P95 threshold',
        value: summary ? `${formatMetric(summary.p95.thresholdMs)} ms` : '—',
      },
      { label: 'Inference', value: formatP95Inference(summary) },
      {
        label: 'Accuracy',
        value:
          summary && typeof summary.accuracy.value === 'number'
            ? `${formatMetric(summary.accuracy.value * 100)}%`
            : '—',
      },
      {
        label: 'Accuracy threshold',
        value: summary ? `${formatMetric(summary.accuracy.threshold * 100)}%` : '—',
      },
      { label: 'Accuracy inference', value: formatAccuracyInference(summary) },
    ];
  }

  function buildUsageSummaryRows(summary: UsageSummary | null): SummaryRow[] {
    return [
      { label: 'Method', value: importMethod ?? '—' },
      { label: 'Total tokens in', value: formatUsageValue(summary?.tokensIn, 0) },
      { label: 'Total tokens out', value: formatUsageValue(summary?.tokensOut, 0) },
      { label: 'API calls', value: formatUsageValue(summary?.apiCalls, 0) },
      { label: 'CPU time', value: formatUsageValueWithUnit(summary?.cpuMs, 'ms') },
      { label: 'RAM footprint', value: formatUsageValueWithUnit(summary?.ramMbSeconds, 'MB·s') },
    ];
  }

  function buildSummaryTable(rows: SummaryRow[]): string {
    return rows
      .map(({ label, value }) => `${label}\t${value}`)
      .join('\n');
  }

  async function copySummaryToClipboard(section: 'performance' | 'usage') {
    const isBrowser = typeof navigator !== 'undefined';
    const clipboard = isBrowser ? navigator.clipboard : undefined;
    if (!clipboard?.writeText) {
      return;
    }

    const rows =
      section === 'performance'
        ? buildPerformanceSummaryRows(importPerformanceSummary)
        : buildUsageSummaryRows(importUsageSummary);

    try {
      await clipboard.writeText(buildSummaryTable(rows));
    } catch (error) {
      console.error('Failed to copy summary to clipboard', error);
    }
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

  function normaliseShowResults(value: unknown): ShowResults {
    if (typeof value === 'boolean') {
      return value ? 'SHOW_FAILED_ONLY' : 'SHOW_ALL';
    }

    if (typeof value === 'string') {
      const normalized = value.trim().toUpperCase();
      if (SHOW_RESULTS_VALUES.includes(normalized as ShowResults)) {
        return normalized as ShowResults;
      }
    }

    return 'SHOW_ALL';
  }

  onMount(async () => {
    try {
      const data = await fetchFixtures(baseUrl);
      fixtures = data;
      showResults = normaliseShowResults(data?.showResults ?? (data as { showFailedOnly?: boolean })?.showFailedOnly);

      const initialMode = typeof data.mode === 'string' ? data.mode : '';
      interpretationMode = initialMode === 'preferences' ? 'preferences' : 'holiday';
      mode = interpretationMode === 'holiday' && initialMode ? initialMode : 'direct-parse';
      dialogOverrideAllowed = isDialogMode(initialMode);
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

  $: isPreferencesMode = interpretationMode === 'preferences';

  $: if (!dialogOverrideAllowed && !isPreferencesMode && mode !== 'direct-parse') {
    mode = 'direct-parse';
  }

  $: parseMode = isPreferencesMode ? 'preferences' : mode;
  $: latestStatus =
    history[0]?.result?.status ?? (fixtureError ? 'error' : loadingFixtures ? 'loading' : 'success');

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

  function formatStatus(status: string | null): string {
    if (!status) {
      return 'Idle';
    }
    const normalized = status.trim();
    return normalized ? `${normalized[0].toUpperCase()}${normalized.slice(1)}` : 'Idle';
  }

  function statusVariant(status: string | null): 'success' | 'error' | 'loading' | 'idle' {
    if (!status) {
      return 'idle';
    }

    const normalized = status.trim().toLowerCase();
    if (normalized === 'loading') {
      return 'loading';
    }

    return isFailureStatus(normalized) ? 'error' : 'success';
  }

  function shouldDisplayImportedEntry(entry: HolidayResultEntry): boolean {
    if (showResults === 'SUPPRESS') {
      return false;
    }

    if (showResults === 'SHOW_FAILED_ONLY') {
      return isFailureStatus(entry?.result?.status);
    }

    return true;
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
        mode: parseMode,
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
    importMethod = method?.trim() ? method.trim() : null;
    let processedCount = 0;
    let totalRecords = 0;
    const operationsForSummary: ImportSummaryRequest['operations'] = [];

    const recordImportedEntry = (entry: HolidayResultEntry) => {
      processedCount += 1;
      const operation: ImportOperationPayload = {
        status: entry.result?.status,
        metadata: entry.result?.metadata ?? null,
      };
      operationsForSummary.push(operation);
      if (shouldDisplayImportedEntry(entry)) {
        addEntry(entry);
      }

      if (importProgress) {
        importProgress = {
          processed: processedCount,
          total: totalRecords,
        };
      }
    };

    try {
      const text = await file.text();
      const records = parseCsv(text);
      const recordsWithInput = records.filter((record) => {
        const value = (record['User input'] ?? '').trim();
        return value.length > 0;
      });

      totalRecords = recordsWithInput.length;
      importProgress =
        totalRecords > 0
          ? {
              processed: 0,
              total: totalRecords,
            }
          : null;

      for (const record of recordsWithInput) {
        const userInput = (record['User input'] ?? '').trim();

        const expectedRaw = record['Expected values'] ?? '';
        const expectedValues = parseExpectedValues(expectedRaw);

        try {
          const payload = await parseText(baseUrl, userInput, {
            mode: parseMode,
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

          recordImportedEntry(entry);
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Unable to parse request';
          const failureResult: HolidayResult = {
            status: 'error',
            data: {},
            metadata: { message },
            clarifications: [],
          };
          recordImportedEntry(createEntry('text', failureResult, userInput));
        }
      }
    } finally {
      busy = false;
      target.value = '';
      if (processedCount > 0) {
        try {
          const payload: ImportSummaryRequest = {
            method: importMethod,
            operations: operationsForSummary,
          };
          const summary = await summarizeImport(baseUrl, payload);
          importPerformanceSummary = summary.performance;
          importUsageSummary = summary.usage;
        } catch (error) {
          console.error(error);
          importPerformanceSummary = null;
          importUsageSummary = null;
        }
      } else {
        importPerformanceSummary = null;
        importUsageSummary = null;
        importMethod = null;
      }
      importProgress = null;
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

    resettingHistory = true;
    try {
      history = [];
      importPerformanceSummary = null;
      importUsageSummary = null;

      if (downloadUrl) {
        URL.revokeObjectURL(downloadUrl);
        downloadUrl = null;
      }
    } finally {
      resettingHistory = false;
    }
  }
</script>

<main class="app">
  <section class="panel">
    <header class="panel-header">
      <div class="panel-title">
        <p class="panel-overline">{isPreferencesMode ? 'Preferences' : 'Holiday request'}</p>
        <h1>{isPreferencesMode ? 'Preferences Console' : 'Holiday Search Console'}</h1>
      </div>
      <div class={`panel-status ${statusVariant(latestStatus)}`} aria-live="polite" data-testid="panel-status">
        <span class="status-dot" aria-hidden="true"></span>
        <span>Status: {formatStatus(latestStatus)}</span>
      </div>
    </header>

    {#if loadingFixtures}
      <p class="info-banner" data-testid="fixtures-loading">Loading fixtures…</p>
    {:else if fixtureError}
      <p class="info-banner error" data-testid="fixtures-error">{fixtureError}</p>
    {:else if fixtures && !isPreferencesMode}
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
    <div class="mode-toggle" role="group" aria-label="Console mode" data-testid="mode-toggle">
      <button
        type="button"
        class:selected={!isPreferencesMode}
        on:click={() => (interpretationMode = 'holiday')}
        data-testid="mode-toggle-holiday"
      >
        Holiday request
      </button>
      <button
        type="button"
        class:selected={isPreferencesMode}
        on:click={() => (interpretationMode = 'preferences')}
        data-testid="mode-toggle-preferences"
      >
        Preferences
      </button>
    </div>
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

      {#if dialogOverrideAllowed && !isPreferencesMode}
        <label>
          Interaction mode
          <select bind:value={mode} data-testid="mode-select">
            <option value="direct-parse">Direct parse</option>
            <option value="dialog">Dialog</option>
          </select>
        </label>
      {/if}

      <label class="full-width">
        {isPreferencesMode ? 'Add your preferences' : 'Ask for a holiday'}
        <textarea
          bind:value={query}
          rows="3"
          placeholder={
            isPreferencesMode
              ? 'Add preferences like no catering, scuba required, wifi everywhere'
              : 'Find me a trip from Amsterdam to Chile next October'
          }
          data-testid="query-input"
        ></textarea>
      </label>

      <div class="actions">
        <button class="button primary" type="submit" disabled={busy} data-testid="submit-button">
          {busy ? 'Parsing…' : 'Parse request'}
        </button>
        <button
          class="button secondary"
          type="button"
          on:click={triggerImport}
          disabled={busy}
          data-testid="import-button"
        >
          Import CSV
        </button>
        <button class="button ghost" type="button" on:click={exportCsv} data-testid="export-button">
          Export CSV
        </button>
      </div>

      {#if importProgress}
        <p class="import-progress" data-testid="import-progress">
          Importing {importProgress.processed} of {importProgress.total}
          {#if importProgress.total > 0}
            ({Math.round((importProgress.processed / importProgress.total) * 100)}%)
          {/if}
        </p>
      {/if}
    </form>

    <MicrophoneWidget
      on:voiceResult={handleVoice}
      {handleVoiceUpload}
      mode={parseMode}
      voiceEnabled={fixtures?.voiceEnabled ?? true}
    />

    <div class="reset-actions">
      <button
        type="button"
        class="button ghost reset-button"
        on:click={resetHistory}
        disabled={!history.length}
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
          <div class="summary-header">
            <h2>Performance summary</h2>
            <button
              type="button"
              class="summary-copy-button"
              on:click={() => copySummaryToClipboard('performance')}
              aria-label="Copy performance summary"
              data-testid="performance-copy-button"
              title="Copy summary as table"
              disabled={!importPerformanceSummary}
            >
              Copy
            </button>
          </div>
          <dl>
            <div class="metric-row">
              <dt>Method</dt>
              <dd data-testid="performance-method">{importPerformanceSummary?.method ?? '—'}</dd>
            </div>
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
                  {#if importPerformanceSummary.p95.valueMs !== null}
                    {formatMetric(importPerformanceSummary.p95.valueMs)} ms
                  {:else}
                    —
                  {/if}
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>P95 threshold</dt>
              <dd data-testid="performance-threshold">
                {#if importPerformanceSummary}
                  {formatMetric(importPerformanceSummary.p95.thresholdMs)} ms
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>Inference</dt>
              <dd data-testid="performance-inference">{formatP95Inference(importPerformanceSummary)}</dd>
            </div>
            <div class="metric-row">
              <dt>Accuracy</dt>
              <dd data-testid="performance-accuracy">
                {#if importPerformanceSummary}
                  {#if typeof importPerformanceSummary.accuracy.value === 'number'}
                    {formatMetric(importPerformanceSummary.accuracy.value * 100)}%
                  {:else}
                    —
                  {/if}
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>Accuracy threshold</dt>
              <dd data-testid="performance-accuracy-threshold">
                {#if importPerformanceSummary}
                  {formatMetric(importPerformanceSummary.accuracy.threshold * 100)}%
                {:else}
                  —
                {/if}
              </dd>
            </div>
            <div class="metric-row">
              <dt>Accuracy inference</dt>
              <dd data-testid="performance-accuracy-inference">
                {formatAccuracyInference(importPerformanceSummary)}
              </dd>
            </div>
          </dl>
        </section>

        <section class="summary-card usage-summary" data-testid="usage-summary">
          <div class="summary-header">
            <h2>Usage footprint summary</h2>
            <button
              type="button"
              class="summary-copy-button"
              on:click={() => copySummaryToClipboard('usage')}
              aria-label="Copy usage summary"
              data-testid="usage-copy-button"
              title="Copy summary as table"
              disabled={!importUsageSummary}
            >
              Copy
            </button>
          </div>
          <dl>
            <div class="metric-row">
              <dt>Method</dt>
              <dd data-testid="usage-method">{importMethod ?? '—'}</dd>
            </div>
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
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    background: linear-gradient(135deg, #0b1224, #0d1f37 60%, #0a152b);
    color: #e6ecf7;
    min-height: 100vh;
  }

  .app {
    display: grid;
    grid-template-columns: minmax(320px, 420px) 1fr;
    gap: 1.75rem;
    min-height: 100vh;
    padding: 1.75rem;
    box-sizing: border-box;
    align-items: start;
  }

  .panel {
    background: linear-gradient(160deg, rgba(31, 41, 71, 0.7), rgba(15, 26, 46, 0.9));
    border-radius: 16px;
    padding: 1.35rem 1.4rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    position: sticky;
    top: 1.75rem;
    align-self: start;
    max-height: calc(100vh - 3.5rem);
    overflow-y: auto;
    border: 1px solid rgba(96, 121, 173, 0.25);
    box-shadow: 0 25px 60px rgba(0, 0, 0, 0.35);
  }

  .panel-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .panel-title {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .panel-overline {
    margin: 0;
    font-size: 0.8rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #95a8d8;
  }

  .panel h1 {
    margin: 0;
    font-size: 1.6rem;
    letter-spacing: 0.01em;
  }

  .info-banner {
    margin: 0;
    padding: 0.85rem 1rem;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(148, 197, 250, 0.15);
    color: #d0ddff;
    font-weight: 600;
  }

  .info-banner.error {
    border-color: rgba(248, 113, 113, 0.4);
    background: rgba(248, 113, 113, 0.12);
    color: #fecdd3;
  }

  .panel-status {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.55rem 0.9rem;
    border-radius: 999px;
    border: 1px solid rgba(148, 197, 250, 0.35);
    background: rgba(58, 118, 188, 0.15);
    font-weight: 700;
    color: #b8d2ff;
    text-transform: capitalize;
    white-space: nowrap;
  }

  .panel-status .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: currentColor;
    box-shadow: 0 0 0 4px rgba(184, 210, 255, 0.14);
  }

  .panel-status.success {
    border-color: rgba(52, 211, 153, 0.35);
    background: rgba(34, 197, 94, 0.12);
    color: #5ce7b4;
  }

  .panel-status.error {
    border-color: rgba(248, 113, 113, 0.35);
    background: rgba(248, 113, 113, 0.12);
    color: #fca5a5;
  }

  .panel-status.loading,
  .panel-status.idle {
    border-color: rgba(148, 197, 250, 0.35);
    background: rgba(59, 130, 246, 0.12);
    color: #bfdbfe;
  }

  .mode-toggle {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.5rem;
  }

  .mode-toggle button {
    background: rgba(255, 255, 255, 0.03);
    color: #e9efff;
    border: 1px solid rgba(126, 148, 196, 0.45);
    border-radius: 12px;
    padding: 0.75rem 0.9rem;
    cursor: pointer;
    font-weight: 700;
    letter-spacing: 0.02em;
    transition: all 120ms ease;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
  }

  .mode-toggle button.selected {
    background: linear-gradient(135deg, #31548f, #203a6a);
    border-color: rgba(142, 201, 255, 0.8);
    color: #dce8ff;
    box-shadow: 0 10px 25px rgba(20, 48, 91, 0.35);
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
    background: radial-gradient(circle at 20% 20%, rgba(49, 84, 143, 0.15), transparent 40%),
      linear-gradient(135deg, rgba(9, 13, 24, 0.75), rgba(13, 27, 51, 0.9));
    border-radius: 18px;
    z-index: -1;
    pointer-events: none;
  }

  .summary-card {
    background: rgba(17, 27, 48, 0.92);
    border: 1px solid rgba(114, 147, 205, 0.35);
    border-radius: 16px;
    padding: 1.1rem 1.3rem;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 0.8rem;
    box-shadow: 0 25px 60px rgba(7, 13, 26, 0.55);
  }

  .summary-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
  }

  .summary-card h2 {
    margin: 0;
    font-size: 1.2rem;
    text-align: left;
    letter-spacing: 0.02em;
    flex: 1;
  }

  .summary-copy-button {
    border: 1px solid rgba(148, 163, 184, 0.6);
    border-radius: 8px;
    background: rgba(59, 130, 246, 0.15);
    color: #bfdbfe;
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
    cursor: pointer;
    transition: background 150ms ease, border-color 150ms ease;
  }

  .summary-copy-button:hover {
    background: rgba(59, 130, 246, 0.25);
    border-color: rgba(59, 130, 246, 0.6);
  }

  .summary-copy-button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
    background: rgba(148, 163, 184, 0.15);
  }

  .summary-card dl {
    margin: 0;
    width: 100%;
    display: grid;
    gap: 0.55rem;
  }

  .summary-card .metric-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.45rem;
    align-items: baseline;
  }

  .summary-card dt {
    font-size: 0.65rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #9fb4dd;
    text-align: left;
  }

  .summary-card dd {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 600;
    text-align: right;
    color: #e9efff;
  }

  .fixtures {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    font-size: 0.95rem;
    padding: 0.75rem 0.85rem;
    border-radius: 12px;
    border: 1px solid rgba(148, 197, 250, 0.18);
    background: rgba(255, 255, 255, 0.03);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
  }

  .query {
    display: grid;
    gap: 1rem;
  }

  label {
    display: grid;
    gap: 0.35rem;
    font-size: 0.95rem;
    color: #c8d7ff;
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
    padding: 0.75rem 0.85rem;
    border-radius: 12px;
    border: 1px solid #233455;
    background: #0c152b;
    color: #e9efff;
    transition: border-color 120ms ease, box-shadow 120ms ease;
  }

  textarea:focus,
  input:focus,
  select:focus {
    outline: none;
    border-color: #5ab7ff;
    box-shadow: 0 0 0 3px rgba(90, 183, 255, 0.25);
  }

  .actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .import-progress {
    margin: 0;
    margin-top: 0.5rem;
    font-size: 0.9rem;
    color: #a9c9ff;
  }

  button {
    font: inherit;
  }

  .button {
    padding: 0.75rem 1rem;
    border-radius: 12px;
    border: 1px solid #233455;
    background: linear-gradient(135deg, #152442, #102038);
    color: #e6edff;
    cursor: pointer;
    transition: transform 120ms ease, box-shadow 150ms ease, border-color 120ms ease;
    font-weight: 700;
    letter-spacing: 0.01em;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.25);
  }

  .button.primary {
    background: linear-gradient(135deg, #5ab7ff, #2f74ff);
    border-color: #5ab7ff;
    color: #0b1324;
    box-shadow: 0 18px 30px rgba(47, 116, 255, 0.35);
  }

  .button.secondary {
    background: linear-gradient(135deg, #234c72, #1b3957);
    border-color: #4a7cb5;
  }

  .button.ghost {
    background: rgba(255, 255, 255, 0.05);
    border-color: #2c3f63;
    color: #d6e4ff;
  }

  .button:hover:enabled {
    transform: translateY(-1px);
    box-shadow: 0 18px 28px rgba(0, 0, 0, 0.35);
    border-color: #5ab7ff;
  }

  .button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .reset-actions {
    margin-top: auto;
    padding-top: 0.25rem;
  }

  .reset-button {
    border-color: rgba(214, 228, 255, 0.35);
    color: #d6e4ff;
    background: rgba(255, 255, 255, 0.04);
    padding-inline: 1.25rem;
  }

  .reset-button:hover:enabled {
    border-color: #5ab7ff;
    color: #5ab7ff;
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

