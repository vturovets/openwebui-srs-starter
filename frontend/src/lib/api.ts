import type { Fixtures, HolidayResult, VoiceResponse } from './types';

async function handleResponse(response: Response) {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Request failed');
  }
  return response.json();
}

export async function fetchFixtures(baseUrl: string): Promise<Fixtures> {
  const response = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/fixtures`);
  const payload = await handleResponse(response);
  return payload as Fixtures;
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

