import type {
  Fixtures,
  FixturesPerformanceTargets,
  HolidayResult,
  ImportJobLifecycleStatus,
  ImportJobProgress,
  ImportJobStatusResponse,
  ImportJobSubmissionResponse,
  ImportJobValidationError,
  UsageMetricKey,
  UsageSummary,
  VoiceResponse,
  PerformanceSummary,
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
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Request failed');
  }
  return response.json();
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

const IMPORT_STATUS_ALIASES: Record<string, ImportJobLifecycleStatus> = {
  pending: 'pending',
  submitted: 'pending',
  created: 'pending',
  waiting: 'queued',
  queued: 'queued',
  queueing: 'queued',
  scheduling: 'queued',
  scheduled: 'queued',
  processing: 'processing',
  running: 'processing',
  'in-progress': 'processing',
  inprogress: 'processing',
  working: 'processing',
  complete: 'completed',
  completed: 'completed',
  success: 'completed',
  succeeded: 'completed',
  finished: 'completed',
  failed: 'failed',
  error: 'failed',
  errored: 'failed',
  cancelled: 'cancelled',
  canceled: 'cancelled',
};

function normaliseImportStatus(value: unknown): ImportJobLifecycleStatus {
  if (typeof value === 'string' && value.trim()) {
    const key = value.trim().toLowerCase();
    return IMPORT_STATUS_ALIASES[key] ?? 'processing';
  }
  return 'processing';
}

function normaliseImportIdentifier(record: Record<string, unknown>): string {
  const id = record.id;
  const jobId = record.jobId ?? record.jobID ?? record.job_id;
  if (typeof id === 'string' && id.trim()) {
    return id.trim();
  }
  if (typeof jobId === 'string' && jobId.trim()) {
    return jobId.trim();
  }
  throw new Error('Import job response missing identifier');
}

function normaliseImportJobSubmission(payload: unknown): ImportJobSubmissionResponse {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Invalid import job response');
  }
  const record = payload as Record<string, unknown>;
  const id = normaliseImportIdentifier(record);
  const status = normaliseImportStatus(record.status);
  const message = typeof record.message === 'string' ? record.message : undefined;
  return { id, status, message };
}

function normaliseImportJobProgress(value: unknown): ImportJobProgress | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const processed = toFiniteNumber(record.processed);
  const total = toFiniteNumber(record.total);
  if (processed === null && total === null) {
    return null;
  }
  return {
    processed: processed !== null ? Math.max(0, Math.floor(processed)) : 0,
    total: total !== null ? Math.max(0, Math.floor(total)) : null,
  };
}

function normaliseUsageSummary(value: unknown): UsageSummary | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const summary: UsageSummary = {};
  const metrics: UsageMetricKey[] = ['tokensIn', 'tokensOut', 'apiCalls', 'cpuMs', 'ramMbSeconds'];
  for (const metric of metrics) {
    const numericValue = toFiniteNumber(record[metric]);
    if (numericValue !== null) {
      summary[metric] = numericValue;
    }
  }
  return Object.keys(summary).length ? summary : null;
}

function asThresholdAssessment(value: unknown): PerformanceSummary['assessment'] {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const thresholdMs = toFiniteNumber(record.thresholdMs);
  const sampleP95 = toFiniteNumber(record.sampleP95);
  if (thresholdMs === null || sampleP95 === null) {
    return null;
  }
  const standardError = toFiniteNumber(record.standardErrorMs);
  const zScore = toFiniteNumber(record.zScore);
  const inference = typeof record.inference === 'string' ? record.inference : null;
  const significantBreach =
    typeof record.significantBreach === 'boolean'
      ? record.significantBreach
      : null;
  const thresholdBreached = typeof record.thresholdBreached === 'boolean' ? record.thresholdBreached : false;
  if (
    inference !== 'meets-target' &&
    inference !== 'violates-target' &&
    inference !== 'inconclusive'
  ) {
    return null;
  }
  return {
    sampleP95,
    standardErrorMs: standardError,
    thresholdMs,
    thresholdBreached,
    significantBreach,
    zScore,
    inference,
  };
}

function normalisePerformanceSummary(value: unknown): PerformanceSummary | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const record = value as Record<string, unknown>;
  const requestCount = toFiniteNumber(record.requestCount) ?? 0;
  const meanResponseMs = toFiniteNumber(record.meanResponseMs) ?? 0;
  const p95ResponseMs = toFiniteNumber(record.p95ResponseMs);
  const accuracy = toFiniteNumber(record.accuracy) ?? 0;
  const thresholdMs = toFiniteNumber(record.thresholdMs) ?? 0;
  const thresholdBreached = typeof record.thresholdBreached === 'boolean'
    ? record.thresholdBreached
    : ((): boolean => {
        const numeric = toFiniteNumber(record.thresholdBreached);
        return numeric !== null ? Boolean(numeric) : false;
      })();
  const sampleSize = toFiniteNumber(record.sampleSize) ?? 0;
  const significance = toFiniteNumber(record.significance) ?? 0;
  const inference =
    typeof record.inference === 'string' &&
    (record.inference === 'meets-target' ||
      record.inference === 'violates-target' ||
      record.inference === 'inconclusive')
      ? (record.inference as PerformanceSummary['inference'])
      : null;
  const assessment = asThresholdAssessment(record.assessment);
  const standardErrorMs = toFiniteNumber(record.standardErrorMs);
  const significantBreach =
    typeof record.significantBreach === 'boolean'
      ? record.significantBreach
      : null;
  const zScore = toFiniteNumber(record.zScore);

  return {
    requestCount,
    meanResponseMs,
    p95ResponseMs: p95ResponseMs !== null ? p95ResponseMs : null,
    accuracy,
    thresholdMs,
    thresholdBreached,
    sampleSize,
    significance,
    inference,
    assessment,
    standardErrorMs,
    significantBreach,
    zScore,
  };
}

function normaliseValidationErrors(value: unknown): ImportJobValidationError[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const errors: ImportJobValidationError[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== 'object') {
      continue;
    }
    const record = entry as Record<string, unknown>;
    const message = record.message;
    if (typeof message !== 'string' || !message.trim()) {
      continue;
    }
    const rowValue = toFiniteNumber(record.row);
    errors.push({
      message: message.trim(),
      row: rowValue !== null ? Math.max(0, Math.floor(rowValue)) : null,
    });
  }
  return errors;
}

function normaliseImportJobStatusPayload(payload: unknown): ImportJobStatusResponse {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Invalid import job status response');
  }
  const record = payload as Record<string, unknown>;
  const id = normaliseImportIdentifier(record);
  const status = normaliseImportStatus(record.status);
  const message = typeof record.message === 'string' ? record.message : undefined;
  const errorCode = typeof record.errorCode === 'string' ? record.errorCode : undefined;
  const queuePositionValue = toFiniteNumber(record.queuePosition ?? record.queue_position);
  const progress = normaliseImportJobProgress(record.progress);
  const performanceSummary = normalisePerformanceSummary(record.performanceSummary);
  const usageSummary = normaliseUsageSummary(record.usageSummary);
  const validationErrors = normaliseValidationErrors(record.validationErrors);

  return {
    id,
    status,
    message,
    errorCode,
    queuePosition: queuePositionValue !== null ? queuePositionValue : null,
    progress,
    performanceSummary: performanceSummary ?? null,
    usageSummary: usageSummary ?? null,
    validationErrors: validationErrors.length ? validationErrors : undefined,
  };
}

function createAbortError(): Error {
  const error = new Error('Operation aborted');
  error.name = 'AbortError';
  return error;
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) {
    return Promise.reject(createAbortError());
  }
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      if (signal) {
        signal.removeEventListener('abort', onAbort);
      }
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      if (signal) {
        signal.removeEventListener('abort', onAbort);
      }
      reject(createAbortError());
    };
    if (signal) {
      signal.addEventListener('abort', onAbort, { once: true });
    }
  });
}

const FINAL_IMPORT_STATUSES: ImportJobLifecycleStatus[] = ['completed', 'failed', 'cancelled'];

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

  const sampleSize = toFiniteNumber(record.importP95SampleSize);
  if (sampleSize !== null) {
    targets.importP95SampleSize = Math.max(0, Math.floor(sampleSize));
  }

  const significance = toFiniteNumber(record.importP95Significance);
  if (significance !== null) {
    targets.importP95Significance = significance;
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

export async function createImportJob(
  baseUrl: string,
  file: File
): Promise<ImportJobSubmissionResponse> {
  const endpoint = `${baseUrl.replace(/\/$/, '')}/v1/imports`;
  const formData = new FormData();
  const fileName = typeof file.name === 'string' && file.name ? file.name : 'import.csv';
  formData.append('file', file, fileName);
  const response = await fetch(endpoint, {
    method: 'POST',
    body: formData,
  });
  const payload = await handleResponse(response);
  return normaliseImportJobSubmission(payload);
}

export async function getImportJobStatus(
  baseUrl: string,
  jobId: string
): Promise<ImportJobStatusResponse> {
  const endpoint = `${baseUrl.replace(/\/$/, '')}/v1/imports/${encodeURIComponent(jobId)}`;
  const response = await fetch(endpoint);
  const payload = await handleResponse(response);
  return normaliseImportJobStatusPayload(payload);
}

export async function pollImportJob(
  baseUrl: string,
  jobId: string,
  options: {
    intervalMs?: number;
    signal?: AbortSignal;
    onUpdate?: (status: ImportJobStatusResponse) => void;
  } = {}
): Promise<ImportJobStatusResponse> {
  const interval = Math.max(250, options.intervalMs ?? 1500);
  const { signal, onUpdate } = options;
  while (true) {
    if (signal?.aborted) {
      throw createAbortError();
    }
    const status = await getImportJobStatus(baseUrl, jobId);
    onUpdate?.(status);
    if (signal?.aborted) {
      throw createAbortError();
    }
    if (FINAL_IMPORT_STATUSES.includes(status.status)) {
      return status;
    }
    await delay(interval, signal);
  }
}

