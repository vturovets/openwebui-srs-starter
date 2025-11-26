import type {
  Fixtures,
  FixturesPerformanceTargets,
  HolidayResult,
  VoiceResponse,
} from './types';

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
  if (response.ok) {
    return response.json();
  }

  const raw = await response.text();
  let message = '';

  if (raw) {
    try {
      const payload = JSON.parse(raw) as Record<string, unknown>;
      const detail = payload?.detail ?? payload?.message ?? payload?.error;
      if (typeof detail === 'string' && detail.trim()) {
        message = detail.trim();
      } else {
        message = raw;
      }
    } catch {
      message = raw;
    }
  }

  throw new Error(message || 'Request failed');
}

type FixturesPayload = Omit<Fixtures, 'airports' | 'destinations'> & {
  airports?: unknown;
  destinations?: unknown;
  performanceTargets?: unknown;
};

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

function normalisePerformanceTargets(
  value: unknown
): FixturesPerformanceTargets | undefined {
  if (!value || typeof value !== 'object') {
    return undefined;
  }

  const record = value as Record<string, unknown>;
  const targets: FixturesPerformanceTargets = {};

  const threshold = toFiniteNumber(record.importP95ThresholdMs);
  if (threshold !== null) {
    targets.importP95ThresholdMs = threshold;
  }

  const outlierThreshold = toFiniteNumber(record.p95OutliersThresholdMs);
  if (outlierThreshold !== null) {
    targets.p95OutliersThresholdMs = Math.max(0, Math.floor(outlierThreshold));
  }

  const accuracyThreshold = toFiniteNumber(record.importAccuracyThreshold);
  if (accuracyThreshold !== null) {
    targets.importAccuracyThreshold = accuracyThreshold;
  }

  const minSampleSize = toFiniteNumber(record.minSampleSize);
  if (minSampleSize !== null) {
    targets.minSampleSize = Math.max(0, Math.floor(minSampleSize));
  }

  const alpha = toFiniteNumber(record.alpha);
  if (alpha !== null) {
    targets.alpha = alpha;
  }

  return Object.keys(targets).length > 0 ? targets : undefined;
}

export async function fetchFixtures(baseUrl: string): Promise<Fixtures> {
  const response = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/fixtures`);
  const payload = await handleResponse(response);
  const fixtures = payload as FixturesPayload;

  return {
    ...fixtures,
    airports: normaliseFixtureNames(fixtures.airports),
    destinations: normaliseFixtureNames(fixtures.destinations),
    performanceTargets: normalisePerformanceTargets(fixtures.performanceTargets),
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

