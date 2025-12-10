export const CSV_LOG_FIELDS = [
  'User input',
  'Extracted values',
] as const;

export type CsvLogField = (typeof CSV_LOG_FIELDS)[number];

export type FilterSpan = {
  text?: string;
  start?: number;
  end?: number;
};

export type MappedFilterOption = {
  optionId: string;
  optionLabel?: string;
  selected?: boolean;
  confidence?: number | null;
  spans?: FilterSpan[];
};

export type MappedFilter = {
  filterId: string;
  filterLabel?: string;
  options?: MappedFilterOption[];
};

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
  filters?: MappedFilter[];
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

export type ShowResults = 'SHOW_FAILED_ONLY' | 'SUPPRESS' | 'SHOW_ALL';

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
  showResults?: ShowResults;
  mode: string;
  llmMethod: string | null;
  llmMethodAlias?: string | null;
  availableMethods?: MethodMetadata[];
  defaultMethod?: string | null;
  methodDefaults?: Record<string, unknown>;
  configuration?: FixturesConfiguration;
  performanceTargets?: FixturesPerformanceTargets;
};

export type ImportOperationPayload = {
  status?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type ImportSummaryRequest = {
  method?: string | null;
  operations: ImportOperationPayload[];
};

export type P95Summary = {
  valueMs: number | null;
  ciLowMs: number | null;
  ciHighMs: number | null;
  thresholdMs: number;
  inference: 'meet-target' | 'above-target' | 'insufficient-data';
  confidenceLevel: number;
  sampleSize: number;
  consideredCount: number;
};

export type AccuracySummary = {
  value: number | null;
  threshold: number;
  pValue: number | null;
  inference: 'meet-target' | 'below-target' | 'insufficient-data';
  confidenceLevel: number;
  sampleSize: number;
  successCount: number;
};

export type ImportPerformanceSummary = {
  method: string | null;
  requestCount: number;
  meanResponseMs: number | null;
  p95: P95Summary;
  accuracy: AccuracySummary;
};

export type UsageSummary = {
  tokensIn?: number;
  tokensOut?: number;
  apiCalls?: number;
  cpuMs?: number;
  ramMbSeconds?: number;
};

export type ImportSummaryResponse = {
  performance: ImportPerformanceSummary;
  usage: UsageSummary;
};

