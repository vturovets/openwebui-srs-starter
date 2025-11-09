import type { Fixtures, HolidayResult, VoiceResponse } from './types';

function normaliseFixtureNames(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((entry) => {
      if (typeof entry === 'string') {
        return entry;
      }

      if (entry && typeof entry === 'object' && 'name' in entry) {
        const name = (entry as { name?: unknown }).name;
        if (typeof name === 'string' && name.trim().length > 0) {
          return name.trim();
        }
      }

      return '';
    })
    .filter((name) => name.length > 0);
}

async function handleResponse(response: Response) {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Request failed');
  }
  return response.json();
}

type FixturesPayload = Omit<Fixtures, 'airports' | 'destinations'> & {
  airports?: unknown;
  destinations?: unknown;
};

export async function fetchFixtures(baseUrl: string): Promise<Fixtures> {
  const response = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/fixtures`);
  const payload = await handleResponse(response);
  const fixtures = payload as FixturesPayload;

  return {
    ...fixtures,
    airports: normaliseFixtureNames(fixtures.airports),
    destinations: normaliseFixtureNames(fixtures.destinations),
  };
}

export async function parseText(
  baseUrl: string,
  text: string,
  options: { mode?: string; method?: string }
): Promise<HolidayResult> {
  const response = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/parse`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      text,
      mode: options.mode,
      method: options.method,
    }),
  });
  return handleResponse(response);
}

export async function postVoice(baseUrl: string, formData: FormData): Promise<VoiceResponse> {
  const response = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/voice`, {
    method: 'POST',
    body: formData,
  });
  const payload = (await handleResponse(response)) as Record<string, unknown>;
  if (
    typeof payload.voiceEnabled === 'undefined' &&
    typeof payload.voice_enabled === 'boolean'
  ) {
    payload.voiceEnabled = payload.voice_enabled as boolean;
  }
  return payload as VoiceResponse;
}

