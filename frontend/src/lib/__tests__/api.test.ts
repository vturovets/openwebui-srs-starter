import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchFixtures } from '../api';

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
