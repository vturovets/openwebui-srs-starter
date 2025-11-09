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
}));

import App from '../App.svelte';
import { fetchFixtures, parseText } from '../lib/api';
import { CSV_LOG_FIELDS } from '../lib/types';

const FIXTURE_RESPONSE = {
  airports: ['Amsterdam', 'London Gatwick'],
  destinations: ['Italy'],
  voiceEnabled: true,
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

  beforeEach(() => {
    fetchFixturesMock.mockReset().mockResolvedValue({ ...FIXTURE_RESPONSE });
    parseTextMock.mockReset();
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
      const indicesFor = (field: (typeof CSV_LOG_FIELDS)[number]) =>
        CSV_LOG_FIELDS.reduce<number[]>((acc, value, index) => {
          if (value === field) {
            acc.push(index);
          }
          return acc;
        }, []);

      expect(rowValues[indexFor('Pipeline Status')]).toBe('Success');
      expect(rowValues[indexFor('User input')]).toBe('Find a trip');
      expect(rowValues[indexFor('Request type')]).toBe('Text');
      expect(rowValues[indexFor('Method')]).toBe('rules');
      expect(rowValues[indexFor('Interaction Mode')]).toBe('dialog');
      const languageColumns = indicesFor('Language Detection');
      expect(rowValues[languageColumns[0]]).toBe('5.00');
      expect(rowValues[languageColumns[1]]).toBe('en (0.92)');
      expect(rowValues[indexFor('Processing Time')]).toBe('34.00');
      expect(rowValues[indexFor('Extraction')]).toBe('10.00');
      expect(rowValues[indexFor('Mapping')]).toBe('12.00');
      expect(rowValues[indexFor('Validation')]).toBe('7.00');
      expect(rowValues[indexFor('Transcription')]).toBe('');
      expect(rowValues[indexFor('Network Latency')]).toBe('');

      const outputPayload = JSON.parse(rowValues[indexFor('Output JSON')]);
      expect(outputPayload.status).toBe('success');
      expect(outputPayload.data).toEqual({ from: ['AMS'], to: ['Italy'] });
      expect(outputPayload.validation).toEqual({ status: 'passed', errors: [] });

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
      expect(secondRow[indexFor('User input')]).toBe('Another trip');

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

