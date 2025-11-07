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

const FIXTURE_RESPONSE = {
  airports: ['Amsterdam', 'London Gatwick'],
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
    missingFields: ['to'],
    invalidFields: [],
  },
  clarifications: [
    {
      parameter: 'to',
      message: 'Please provide a destination.',
      reason: 'missing',
    },
  ],
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
    expect(screen.getByText('Airports:')).toBeInTheDocument();
    expect(screen.getByText('Amsterdam, London Gatwick')).toBeInTheDocument();
  });

  it('shows structured results with timings after parsing text', async () => {
    parseTextMock.mockResolvedValueOnce(PARSE_SUCCESS);
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
    expect(screen.getByText('totalMs')).toBeInTheDocument();
    expect(screen.getByTestId('status-label')).toHaveTextContent('success');
  });

  it('surfaces clarification prompts when parse fails', async () => {
    parseTextMock.mockResolvedValueOnce(PARSE_FAILED);
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

  it('generates CSV preview with processed history', async () => {
    parseTextMock.mockResolvedValueOnce(PARSE_SUCCESS);
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
    expect(screen.getByTestId('csv-preview')).toBeInTheDocument();
    expect(screen.getByTestId('csv-preview').textContent).toContain('Timestamp,Source,Status');
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

