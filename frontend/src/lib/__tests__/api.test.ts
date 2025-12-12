import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchFixtures, parseText } from '../api';

describe('fetchFixtures', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('normalises airport and destination names from fixture payload', async () => {
    const payload = {
      airports: [
        { id: 'AMS', name: 'Amsterdam', available: true },
        { id: 'LGW', name: 'London Gatwick', available: false },
      ],
      destinations: [
        { id: 'IT', name: 'Italy' },
        { id: 'FR', name: 'France' },
      ],
      voiceEnabled: true,
      mode: 'dialog',
      llmMethod: 'rules',
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    } as Response);

    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    const fixtures = await fetchFixtures('http://localhost:8000');
    expect(fixtures.airports).toEqual(['Amsterdam', 'London Gatwick']);
    expect(fixtures.destinations).toEqual(['Italy', 'France']);
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/v1/fixtures');
  });

  it('preserves performance targets block when provided by backend', async () => {
    const payload = {
      airports: ['Amsterdam'],
      destinations: ['Italy'],
      voiceEnabled: true,
      mode: 'dialog',
      llmMethod: 'rules',
      performanceTargets: {
        importP95ThresholdMs: '1500',
        importP95SampleSize: '500',
        importP95Significance: '0.9',
      },
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    } as Response);

    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    const fixtures = await fetchFixtures('http://localhost:8000/');
    expect(fixtures.performanceTargets).toEqual({
      importP95ThresholdMs: 1500,
      importP95SampleSize: 500,
      importP95Significance: 0.9,
    });
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/v1/fixtures');
  });
});

describe('parseText', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('routes preferences mode requests to dedicated endpoint and normalises response', async () => {
    const payload = {
      status: 'success',
      filters: [{ filterId: 'facilities', filterLabel: 'Facilities', options: [] }],
      metadata: { mode: 'preferences', message: 'ok' },
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    } as Response);

    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    const result = await parseText('http://localhost:8000/', 'wifi', {
      mode: 'preferences',
      method: 'rules-basic',
    });

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/v1/preferences/parse', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text: 'wifi', method: 'rules-basic' }),
    });
    expect(result).toEqual({
      status: 'success',
      data: null,
      metadata: { mode: 'preferences', message: 'ok' },
      filters: payload.filters,
    });
  });

  it('falls back to standard parse endpoint for non-preference modes', async () => {
    const payload = {
      status: 'success',
      data: { destination: 'Spain' },
      metadata: { mode: 'direct-parse' },
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    } as Response);

    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);

    const result = await parseText('http://localhost:8000', 'need a holiday', {
      mode: 'direct-parse',
      method: 'hybrid-v1',
    });

    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/v1/parse', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text: 'need a holiday', mode: 'direct-parse', method: 'hybrid-v1' }),
    });
    expect(result).toEqual(payload);
  });
});
