import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import App from '../App.svelte';

const FIXTURE_RESPONSE = {
  airports: ['AMS', 'LGW'],
  destinations: ['Italy'],
  voiceEnabled: true,
  mode: 'dialog',
  llmMethod: 'rules',
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
    timings: { totalMs: 42 },
    recognizedSummaries: {
      airports: ['AMS'],
      destinations: ['Italy'],
      dates: ['2025-10-10'],
    },
  },
};

const PARSE_FAILED = {
  status: 'failed',
  data: {},
  metadata: {
    mode: 'dialog',
    method: 'rules',
    timings: { totalMs: 42 },
    recognizedSummaries: {
      airports: [],
      destinations: [],
      dates: [],
    },
  },
  clarifications: [
    {
      parameter: 'to',
      message: 'Please provide a destination.',
      reason: 'missing',
    },
  ],
};

function mockFetchSequence(responses: Array<Record<string, unknown>>) {
  const calls = responses.map((payload) =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(payload),
    })
  );
  global.fetch = vi.fn().mockImplementation(() => calls.shift()!);
}

describe('Holiday search console', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchSequence([FIXTURE_RESPONSE]);
  });

  it('loads fixtures on mount and displays airports/destinations', async () => {
    render(App);
    expect(screen.getByTestId('fixtures-loading')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('fixtures-loaded')).toBeInTheDocument());
    expect(screen.getByText('Airports:')).toBeInTheDocument();
    expect(screen.getByText('AMS, LGW')).toBeInTheDocument();
  });

  it('shows structured results with timings after parsing text', async () => {
    mockFetchSequence([FIXTURE_RESPONSE, PARSE_SUCCESS]);
    render(App);
    await waitFor(() => expect(screen.getByTestId('fixtures-loaded')).toBeInTheDocument());

    const input = screen.getByTestId('query-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'Find a trip' } });
    await fireEvent.submit(screen.getByTestId('parse-form'));

    await waitFor(() => expect(screen.getAllByTestId('structured-result').length).toBeGreaterThan(0));
    expect(screen.getByText('totalMs')).toBeInTheDocument();
    expect(screen.getByTestId('status-label')).toHaveTextContent('success');
  });

  it('surfaces clarification prompts when parse fails', async () => {
    mockFetchSequence([FIXTURE_RESPONSE, PARSE_FAILED]);
    render(App);
    await waitFor(() => expect(screen.getByTestId('fixtures-loaded')).toBeInTheDocument());

    const input = screen.getByTestId('query-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'Missing destination' } });
    await fireEvent.submit(screen.getByTestId('parse-form'));

    await waitFor(() => expect(screen.getByTestId('clarification')).toBeInTheDocument());
    expect(screen.getByTestId('issue-summary')).toBeInTheDocument();
  });

  it('generates CSV preview with processed history', async () => {
    mockFetchSequence([FIXTURE_RESPONSE, PARSE_SUCCESS]);
    render(App);
    await waitFor(() => expect(screen.getByTestId('fixtures-loaded')).toBeInTheDocument());

    const input = screen.getByTestId('query-input') as HTMLTextAreaElement;
    await fireEvent.input(input, { target: { value: 'Find a trip' } });
    await fireEvent.submit(screen.getByTestId('parse-form'));
    await waitFor(() => expect(screen.getByTestId('structured-result')).toBeInTheDocument());

    await fireEvent.click(screen.getByTestId('export-button'));
    expect(screen.getByTestId('csv-preview')).toBeInTheDocument();
    expect(screen.getByTestId('csv-preview').textContent).toContain('Timestamp,Source,Status');
  });
});

