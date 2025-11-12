import type { PerformanceInference, ThresholdAssessment } from './performance';

export const CSV_LOG_FIELDS = [
  'User input',
  'Extracted values',
] as const;

export type CsvLogField = (typeof CSV_LOG_FIELDS)[number];

export type HolidayResult = {
  status: string;
  data: Record<string, unknown> | null;
  metadata: Record<string, any> & {
    timings?: Record<string, number>;
    mode?: string;
    method?: string | null;
    recognizedSummaries?: {
      airports?: string[];
      destinations?: string[];
      dates?: string[];
    };
    missingFields?: string[];
    invalidFields?: string[];
    expectedValueMismatches?: Array<{
      label: string;
      expected: string;
      actual: string;
    }>;
  };
  clarifications?: Array<{ parameter: string; message: string; reason: string }>;
  transcript?: string;
};

export type VoiceWordTiming = {
  word: string;
  start: number;
  end: number;
};

export type VoiceResponse = HolidayResult & {
  voiceEnabled: boolean;
  voice_enabled?: boolean;
  engine: string | null;
  words: VoiceWordTiming[];
};

export type UsageMetricKey = 'tokensIn' | 'tokensOut' | 'apiCalls' | 'cpuMs' | 'ramMbSeconds';

export type UsageSummary = Partial<Record<UsageMetricKey, number>>;

export type PerformanceSummary = {
  requestCount: number;
  meanResponseMs: number;
  p95ResponseMs: number | null;
  accuracy: number;
  thresholdMs: number;
  thresholdBreached: boolean;
  sampleSize: number;
  significance: number;
  inference: PerformanceInference | null;
  assessment: ThresholdAssessment | null;
  standardErrorMs: number | null;
  significantBreach: boolean | null;
  zScore: number | null;
};

export type ImportJobLifecycleStatus =
  | 'pending'
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type ImportJobProgress = {
  processed: number;
  total: number | null;
};

export type ImportJobValidationError = {
  row?: number | null;
  message: string;
};

export type ImportJobSubmissionResponse = {
  id: string;
  status: ImportJobLifecycleStatus;
  message?: string;
};

export type ImportJobStatusResponse = {
  id: string;
  status: ImportJobLifecycleStatus;
  message?: string;
  errorCode?: string;
  queuePosition?: number | null;
  progress?: ImportJobProgress | null;
  performanceSummary?: PerformanceSummary | null;
  usageSummary?: UsageSummary | null;
  validationErrors?: ImportJobValidationError[];
};

export type HolidayResultEntry = {
  id: string;
  source: 'text' | 'voice';
  input: string;
  result: HolidayResult;
  prompt: string;
  timestamp: string;
};

export type MethodMetadata = {
  id: string;
  type: string;
  label: string;
  description?: string;
  params?: Record<string, unknown>;
  [key: string]: unknown;
};

export type FixturesConfigurationDefaults = {
  adults: number;
  nonAdults: number;
};

export type FixturesConfigurationFlexibleOption = {
  id: string;
  name: string;
  isDefault?: boolean;
};

export type FixturesConfigurationFlexibility = {
  isFlexibleAllowed?: boolean;
  flexibleList?: FixturesConfigurationFlexibleOption[];
};

export type FixturesConfiguration = {
  defaults?: FixturesConfigurationDefaults;
  flexibility?: FixturesConfigurationFlexibility;
  [key: string]: unknown;
};

export type FixturesPerformanceTargets = {
  importP95ThresholdMs?: number;
  importP95SampleSize?: number;
  importP95Significance?: number;
};

export type Fixtures = {
  airports: string[];
  destinations: string[];
  durations?: Array<{ id: string; name: string }>;
  voiceEnabled: boolean;
  showFailedOnly?: boolean;
  mode: string;
  llmMethod: string | null;
  llmMethodAlias?: string | null;
  availableMethods?: MethodMetadata[];
  defaultMethod?: string | null;
  methodDefaults?: Record<string, unknown>;
  configuration?: FixturesConfiguration;
  performanceTargets?: FixturesPerformanceTargets;
};

