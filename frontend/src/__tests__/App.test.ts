import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, beforeEach, vi } from 'vitest';

vi.mock('svelte', async () => {
  const actual = await vi.importActual<typeof import('svelte')>('svelte');
  return {
    ...actual,
    onMount: (fn: () => void) => fn(),
  };
});

import { tick } from 'svelte';

vi.mock('../lib/api', () => ({
  fetchFixtures: vi.fn(),
  parseText: vi.fn(),
  postVoice: vi.fn(),
  createImportJob: vi.fn(),
  pollImportJob: vi.fn(),
}));

import App from '../App.svelte';
import { createImportJob, fetchFixtures, parseText, pollImportJob } from '../lib/api';
import { CSV_LOG_FIELDS } from '../lib/types';

const FIXTURE_RESPONSE = {
  airports: ['Amsterdam', 'London Gatwick'],
  destinations: ['Italy'],
  voiceEnabled: true,
  showFailedOnly: true,
  mode: 'dialog',
  llmMethod: 'rules-basic',
  availableMethods: [
    { id: 'rules-basic', type: 'rules', label: 'Rules Basic' },
    { id: 'gpt5-default', type: 'llm', label: 'LLM Default' },
  ],
  defaultMethod: 'rules-basic',
  methodDefaults: { temperature: 0.0 },
  configuration: {
    defaults: {
      adults: 2,
      nonAdults: 0,
    },
    flexibility: {
      isFlexibleAllowed: true,
      flexibleList: [
        { id: '3', name: '+- 3 days', isDefault: true },
        { id: '0', name: 'Not flexible', isDefault: false },
      ],
    },
  },
};

const PARSE_SUCCESS = {
  status: 'success',
  data: {
    from: ['AMS'],
    to: ['Italy'],
  },
  metadata: {
    mode: 'dialog',
    method: 'rules',
    timings: {
      languageMs: 5,
      extractionMs: 10,
      normalizationMs: 12,
      validationMs: 7,
      totalMs: 34,
      thresholdBreached: false,
    },
    recognizedSummaries: {
      airports: ['AMS'],
      destinations: ['Italy'],
      dates: ['2025-10-10'],
    },
    recognizedEntities: {
      airports: ['AMS'],
      destinations: ['Italy'],
      dates: ['2025-10-10'],
      duration: '2007',
      flexibility: '3',
    },
    missingFields: [],
    invalidFields: [],
    validation: { status: 'passed', errors: [] },
    transcript: [{ role: 'user', text: 'Find a trip' }],
    language: { code: 'en', confidence: 0.92 },
    llm: {
      provider: 'openai',
      promptId: 'prompt-1',
      requestId: 'req-1',
      responseId: 'res-1',
    },
    usage: {
      components: [
        {
          name: 'llm',
          usage: {
            tokensIn: 50,
            tokensOut: 10,
            apiCalls: 1,
            cpuMs: 12.5,
            ramMbSeconds: 3.4,
          },
        },
        {
          name: 'validator',
          usage: {
            cpuMs: 7.5,
            ramMbSeconds: 2.1,
          },
        },
      ],
    },
  },
};

const PARSE_FAILED = {
  status: 'failed',
  data: {},
  metadata: {
    mode: 'dialog',
    method: 'rules',
    timings: {
      languageMs: 5,
      extractionMs: 10,
      normalizationMs: 12,
      validationMs: 7,
      totalMs: 34,
      thresholdBreached: false,
    },
    recognizedSummaries: {
      airports: [],
      destinations: [],
      dates: [],
    },
    recognizedEntities: {
      airports: [],
      destinations: [],
      dates: [],
      duration: null,
      flexibility: null,
    },
    missingFields: ['to'],
    invalidFields: [],
    validation: { status: 'failed', errors: [{ message: 'Utterance must include destination' }] },
    transcript: [{ role: 'user', text: 'Missing destination' }],
    language: { code: 'en', confidence: 0.88 },
  },
  clarifications: [
    {
      parameter: 'to',
      message: 'Please provide a destination.',
      reason: 'missing',
    },
  ],
};

const IMPORT_JOB_PROCESSING = {
  id: 'job-123',
  status: 'processing',
  message: 'Processing import',
  progress: { processed: 5, total: 10 },
};

const IMPORT_JOB_COMPLETED = {
  id: 'job-123',
  status: 'completed',
  message: 'Import finished',
  performanceSummary: {
    requestCount: 1,
    meanResponseMs: 34,
    p95ResponseMs: 34,
    accuracy: 100,
    thresholdMs: 1000,
    thresholdBreached: false,
    sampleSize: 1000,
    significance: 0.95,
    inference: 'inconclusive',
    assessment: null,
    standardErrorMs: null,
    significantBreach: null,
    zScore: null,
  },
  usageSummary: {
    tokensIn: 50,
    tokensOut: 10,
    apiCalls: 1,
    cpuMs: 20,
    ramMbSeconds: 5.5,
  },
};

const IMPORT_JOB_FAILED = {
  id: 'job-123',
  status: 'failed',
  message: 'Validation failed',
  validationErrors: [
    { row: 2, message: 'Missing destination' },
    { row: null, message: 'Duplicate header' },
  ],
};

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

const parseCsvLine = (line: string): string[] => {
  const values: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (inQuotes) {
      if (char === '"') {
        if (line[index + 1] === '"') {
          current += '"';
          index += 1;
          continue;
        }
        inQuotes = false;
      } else {
        current += char;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === ',') {
      values.push(current);
      current = '';
    } else {
      current += char;
    }
  }

  values.push(current);
  return values;
};


describe('Holiday search console', () => {
  const fetchFixturesMock = fetchFixtures as unknown as vi.Mock;
  const parseTextMock = parseText as unknown as vi.Mock;
  const createImportJobMock = createImportJob as unknown as vi.Mock;
  const pollImportJobMock = pollImportJob as unknown as vi.Mock;

  beforeEach(() => {
    fetchFixturesMock.mockReset().mockResolvedValue({ ...FIXTURE_RESPONSE });
    parseTextMock.mockReset();
    createImportJobMock.mockReset().mockResolvedValue({
      id: 'job-123',
      status: 'queued',
      message: 'Queued for import',
    });
    pollImportJobMock.mockReset().mockImplementation(async (_baseUrl, _jobId, options = {}) => {
      options?.onUpdate?.(IMPORT_JOB_PROCESSING);
      await Promise.resolve();
      options?.onUpdate?.(IMPORT_JOB_COMPLETED);
      return IMPORT_JOB_COMPLETED;
    });
  });

  it('loads fixtures on mount and displays airports/destinations', async () => {
    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();
    expect(screen.getByTestId('fixtures-loading')).toBeInTheDocument();
    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId('fixtures-loaded')).toBeInTheDocument());
    expect(screen.queryByText('Voice Enabled:')).not.toBeInTheDocument();
    expect(screen.getByText('Default Participants:')).toBeInTheDocument();
    expect(screen.getByText('2 adults / 0 non-adults')).toBeInTheDocument();
    const flexibilityLabel = screen.getByText('Flexibility, days:');
    expect(flexibilityLabel.nextElementSibling?.textContent).toBe('3');
    expect(screen.getByText('Airports:')).toBeInTheDocument();
    expect(screen.getByText('Amsterdam, London Gatwick')).toBeInTheDocument();

    const form = screen.getByTestId('parse-form');
    const labels = Array.from(form.querySelectorAll('label')).map((node) =>
      node.textContent?.replace(/\s+/g, ' ').trim()
    );
    expect(labels[0]).toContain('Method');
    expect(labels[1]).toContain('Interaction mode');

    const methodSelect = screen.getByTestId('method-select') as HTMLSelectElement;
    expect(methodSelect.value).toBe('rules-basic');
  });

  it('hides interaction mode selector when dialog mode is disabled', async () => {
    fetchFixturesMock.mockResolvedValueOnce({
      ...FIXTURE_RESPONSE,
      mode: 'direct-parse',
    });

    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();

    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');

    expect(screen.queryByTestId('mode-select')).not.toBeInTheDocument();
  });

  it('shows structured results with timings after parsing text', async () => {
    parseTextMock.mockResolvedValueOnce(clone(PARSE_SUCCESS));
    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();
    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');

    const input = screen.getByTestId('query-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'Find a trip' } });
    await fireEvent.submit(screen.getByTestId('parse-form'));

    await waitFor(() => expect(screen.getAllByTestId('structured-result').length).toBeGreaterThan(0));
    expect(screen.getByText('Total, ms')).toBeInTheDocument();
    expect(screen.getByTestId('status-label')).toHaveTextContent('success');
  });

  it('surfaces clarification prompts when parse fails', async () => {
    parseTextMock.mockResolvedValueOnce(clone(PARSE_FAILED));
    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();
    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');

    const input = screen.getByTestId('query-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'Missing destination' } });
    await fireEvent.submit(screen.getByTestId('parse-form'));

    await waitFor(() => expect(screen.getByTestId('clarification')).toBeInTheDocument());
    expect(screen.getByTestId('issue-summary')).toBeInTheDocument();
  });

  it('displays performance and usage summaries after import job completes', async () => {
    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();
    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');

    expect(screen.queryByTestId('performance-summary')).not.toBeInTheDocument();
    expect(screen.queryByTestId('usage-summary')).not.toBeInTheDocument();

    const file = new File(
      ['User input,Expected values\n"Find a trip","From: Amsterdam | To: Spain"\n'],
      'requests.csv',
      { type: 'text/csv' }
    );
    const importInput = screen.getByTestId('import-input') as HTMLInputElement;
    Object.defineProperty(importInput, 'files', { value: [file], configurable: true });
    await fireEvent.change(importInput);

    await waitFor(() => expect(createImportJobMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(pollImportJobMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId('performance-summary')).toBeInTheDocument());

    expect(screen.queryByTestId('structured-result')).toBeNull();

    expect(screen.getByTestId('performance-requests')).toHaveTextContent('1');
    expect(screen.getByTestId('performance-mean')).toHaveTextContent('34 ms');
    expect(screen.getByTestId('performance-p95')).toHaveTextContent('34 ms');
    expect(screen.getByTestId('performance-threshold')).toHaveTextContent('1000 ms');
    expect(screen.getByTestId('performance-inference')).toHaveTextContent('Inconclusive');
    expect(screen.getByTestId('performance-accuracy')).toHaveTextContent('100%');

    expect(screen.getByTestId('usage-summary')).toBeInTheDocument();
    expect(screen.getByTestId('usage-tokens-in')).toHaveTextContent('50');
    expect(screen.getByTestId('usage-tokens-out')).toHaveTextContent('10');
    expect(screen.getByTestId('usage-api-calls')).toHaveTextContent('1');
    expect(screen.getByTestId('usage-cpu')).toHaveTextContent('20 ms');
    expect(screen.getByTestId('usage-ram')).toHaveTextContent('5.5 MB·s');

    await waitFor(() => expect(screen.getByTestId('import-status')).toHaveTextContent('Import finished'));

    component.$destroy();
  });

  it('shows import progress while job is processing', async () => {
    pollImportJobMock.mockImplementationOnce(async (_baseUrl, _jobId, options = {}) => {
      options?.onUpdate?.(IMPORT_JOB_PROCESSING);
      await new Promise((resolve) => setTimeout(resolve, 0));
      options?.onUpdate?.(IMPORT_JOB_COMPLETED);
      return IMPORT_JOB_COMPLETED;
    });

    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();
    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');

    const file = new File(['User input,Expected values\n"Find a trip",""\n'], 'requests.csv', {
      type: 'text/csv',
    });
    const importInput = screen.getByTestId('import-input') as HTMLInputElement;
    Object.defineProperty(importInput, 'files', { value: [file], configurable: true });

    await fireEvent.change(importInput);

    await waitFor(() => expect(screen.getByTestId('import-status')).toHaveTextContent('Import in progress'));
    await waitFor(() => expect(screen.getByTestId('import-progress')).toHaveTextContent('5 / 10'));
    await waitFor(() => expect(screen.getByTestId('performance-summary')).toBeInTheDocument());

    component.$destroy();
  });

  it('does not render structured results even when successful imports are allowed', async () => {
    fetchFixturesMock.mockResolvedValueOnce({
      ...FIXTURE_RESPONSE,
      showFailedOnly: false,
    });

    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();

    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');

    const file = new File(['User input,Expected values\n"Find a trip",""\n'], 'requests.csv', {
      type: 'text/csv',
    });
    const importInput = screen.getByTestId('import-input') as HTMLInputElement;
    Object.defineProperty(importInput, 'files', { value: [file], configurable: true });

    await fireEvent.change(importInput);

    await waitFor(() => expect(screen.getByTestId('performance-summary')).toBeInTheDocument());
    expect(screen.queryByTestId('structured-result')).toBeNull();

    component.$destroy();
  });

  it('shows validation errors when the import job fails', async () => {
    pollImportJobMock.mockImplementationOnce(async (_baseUrl, _jobId, options = {}) => {
      options?.onUpdate?.(IMPORT_JOB_PROCESSING);
      await Promise.resolve();
      options?.onUpdate?.(IMPORT_JOB_FAILED);
      return IMPORT_JOB_FAILED;
    });

    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();
    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');

    const file = new File(['User input,Expected values\n"Broken",""\n'], 'requests.csv', { type: 'text/csv' });
    const importInput = screen.getByTestId('import-input') as HTMLInputElement;
    Object.defineProperty(importInput, 'files', { value: [file], configurable: true });

    await fireEvent.change(importInput);

    await waitFor(() => expect(screen.getByTestId('import-error')).toHaveTextContent('Validation failed'));
    const errorList = await screen.findByTestId('import-validation-errors');
    expect(errorList.textContent).toContain('Row 2');
    expect(errorList.textContent).toContain('Missing destination');
    expect(errorList.textContent).toContain('Duplicate header');
    expect(screen.queryByTestId('performance-summary')).not.toBeInTheDocument();
    expect(screen.queryByTestId('usage-summary')).not.toBeInTheDocument();

    component.$destroy();
  });

  it('exports backend-compatible CSV for the current session history', async () => {
    const originalCreateObjectURL = (globalThis.URL as { createObjectURL?: typeof URL.createObjectURL }).createObjectURL;
    const createObjectURLSpy = vi.fn(() => 'blob:mock-url');
    (globalThis.URL as { createObjectURL?: typeof URL.createObjectURL }).createObjectURL =
      createObjectURLSpy as unknown as typeof URL.createObjectURL;
    const originalRevokeObjectURL = (globalThis.URL as { revokeObjectURL?: typeof URL.revokeObjectURL }).revokeObjectURL;
    const revokeObjectURLSpy = vi.fn();
    (globalThis.URL as { revokeObjectURL?: typeof URL.revokeObjectURL }).revokeObjectURL =
      revokeObjectURLSpy as unknown as typeof URL.revokeObjectURL;
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    const originalBlob = globalThis.Blob;
    const blobParts: BlobPart[][] = [];
    class BlobMock extends (originalBlob as typeof Blob) {
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        blobParts.push(parts);
        super(parts, options);
      }
    }
    (globalThis as { Blob: typeof Blob }).Blob = BlobMock as unknown as typeof Blob;

    try {
      parseTextMock.mockResolvedValueOnce(clone(PARSE_SUCCESS));
      const { component } = render(App);
      await tick();
      component.$$.on_mount.forEach((fn) => fn());
      await tick();
      await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
      await screen.findByTestId('fixtures-loaded');

      const input = screen.getByTestId('query-input') as HTMLTextAreaElement;
      await fireEvent.input(input, { target: { value: 'Find a trip' } });
      await fireEvent.submit(screen.getByTestId('parse-form'));
      await waitFor(() => expect(screen.getByTestId('structured-result')).toBeInTheDocument());

      await fireEvent.click(screen.getByTestId('export-button'));
      await waitFor(() => expect(anchorClickSpy).toHaveBeenCalled());

      const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
      expect(blob).toBeInstanceOf(Blob);
      expect(blob.type).toBe('text/csv;charset=utf-8');
      const csvText = (blobParts[0] ?? [])
        .map((part) => (typeof part === 'string' ? part : String(part)))
        .join('')
        .trim();
      const lines = csvText.split('\n');
      expect(lines[0]).toBe(CSV_LOG_FIELDS.join(','));
      expect(lines).toHaveLength(2);

      const rowValues = parseCsvLine(lines[1]);
      const indexFor = (field: (typeof CSV_LOG_FIELDS)[number]) => CSV_LOG_FIELDS.indexOf(field);

      expect(rowValues).toHaveLength(CSV_LOG_FIELDS.length);
      expect(rowValues[indexFor('User input')]).toBe('Find a trip');
      expect(rowValues[indexFor('Extracted values')]).toBe('From: Amsterdam | To: Italy');

      component.$destroy();
      createObjectURLSpy.mockClear();
      anchorClickSpy.mockClear();
      blobParts.length = 0;

      const secondPayload = clone(PARSE_SUCCESS);
      secondPayload.metadata.transcript = [{ role: 'user', text: 'Another trip' }];
      parseTextMock.mockResolvedValueOnce(secondPayload);

      const { component: secondComponent } = render(App);
      await tick();
      secondComponent.$$.on_mount.forEach((fn) => fn());
      await tick();
      await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(2));
      await screen.findByTestId('fixtures-loaded');

      const secondInput = screen.getByTestId('query-input') as HTMLTextAreaElement;
      await fireEvent.input(secondInput, { target: { value: 'Another trip' } });
      await fireEvent.submit(screen.getByTestId('parse-form'));
      await waitFor(() => expect(screen.getByTestId('structured-result')).toBeInTheDocument());

      await fireEvent.click(screen.getByTestId('export-button'));
      await waitFor(() => expect(anchorClickSpy).toHaveBeenCalled());

      const secondBlob = createObjectURLSpy.mock.calls[0][0] as Blob;
      expect(secondBlob).toBeInstanceOf(Blob);
      expect(secondBlob.type).toBe('text/csv;charset=utf-8');
      const secondText = (blobParts[0] ?? [])
        .map((part) => (typeof part === 'string' ? part : String(part)))
        .join('')
        .trim();
      const secondLines = secondText.split('\n');
      expect(secondLines).toHaveLength(2);

      const secondRow = parseCsvLine(secondLines[1]);
      expect(secondRow).toHaveLength(CSV_LOG_FIELDS.length);
      expect(secondRow[indexFor('User input')]).toBe('Another trip');
      expect(secondRow[indexFor('Extracted values')]).toBe('From: Amsterdam | To: Italy');

      secondComponent.$destroy();
    } finally {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
      createObjectURLSpy.mockReset();
      if (originalCreateObjectURL) {
        (globalThis.URL as { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = originalCreateObjectURL;
      } else {
        delete (globalThis.URL as { createObjectURL?: typeof URL.createObjectURL }).createObjectURL;
      }
      revokeObjectURLSpy.mockReset();
      if (originalRevokeObjectURL) {
        (globalThis.URL as { revokeObjectURL?: typeof URL.revokeObjectURL }).revokeObjectURL = originalRevokeObjectURL;
      } else {
        delete (globalThis.URL as { revokeObjectURL?: typeof URL.revokeObjectURL }).revokeObjectURL;
      }
      anchorClickSpy.mockRestore();
      (globalThis as { Blob: typeof Blob }).Blob = originalBlob;
    }
  });

  it('resets the results history when the reset button is clicked', async () => {
    parseTextMock.mockResolvedValueOnce(clone(PARSE_SUCCESS));

    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();

    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');

    const resetButton = screen.getByTestId('reset-button') as HTMLButtonElement;
    expect(resetButton).toBeDisabled();

    const input = screen.getByTestId('query-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'Find a trip' } });
    await fireEvent.submit(screen.getByTestId('parse-form'));

    await waitFor(() => expect(screen.getByTestId('structured-result')).toBeInTheDocument());
    expect(resetButton.disabled).toBe(false);

    const file = new File(['User input,Expected values\n"Find a trip",""\n'], 'requests.csv', {
      type: 'text/csv',
    });
    const importInput = screen.getByTestId('import-input') as HTMLInputElement;
    Object.defineProperty(importInput, 'files', { value: [file], configurable: true });
    await fireEvent.change(importInput);

    await waitFor(() => expect(screen.getByTestId('performance-summary')).toBeInTheDocument());

    await fireEvent.click(resetButton);
    await waitFor(() => expect(screen.getByTestId('empty-state')).toBeInTheDocument());
    expect(screen.queryByTestId('performance-summary')).not.toBeInTheDocument();
    expect(screen.queryByTestId('usage-summary')).not.toBeInTheDocument();
    expect(resetButton).toBeDisabled();

    component.$destroy();
  });

  it('disables voice interactions when voice fixtures are disabled', async () => {
    fetchFixturesMock.mockResolvedValueOnce({
      ...FIXTURE_RESPONSE,
      voiceEnabled: false,
    });

    const { component } = render(App);
    await tick();
    component.$$.on_mount.forEach((fn) => fn());
    await tick();

    await waitFor(() => expect(fetchFixturesMock).toHaveBeenCalledTimes(1));
    await screen.findByTestId('fixtures-loaded');
    await tick();

    await waitFor(() =>
      expect(screen.getByTestId('voice-status')).toHaveTextContent(
        'Voice input is disabled by configuration.'
      )
    );

    await waitFor(() => expect(screen.getByTestId('record-button')).toBeDisabled());

    const uploadInput = screen.getByTestId('voice-input') as HTMLInputElement;
    expect(uploadInput.disabled).toBe(true);
  });
});

