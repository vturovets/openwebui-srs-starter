// NOTE: "Language Detection" is intentionally duplicated. The first column logs the
// timing information reported as `languageMs`, while the second captures the semantic
// detection outcome (language code plus confidence) for downstream analytics.
export const CSV_LOG_FIELDS = [
  'Timestamp (UTC)',
  'User input',
  'Request type',
  'Method',
  'Interaction Mode',
  'Pipeline Status',
  'Language Detection',
  'Processing Time',
  'Language Detection',
  'Extraction',
  'Mapping',
  'Validation',
  'Transcription',
  'Network Latency',
  'Output',
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

export type HolidayResultEntry = {
  id: string;
  source: 'text' | 'voice';
  input: string;
  result: HolidayResult;
  prompt: string;
  timestamp: string;
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

export type Fixtures = {
  airports: string[];
  destinations: string[];
  durations?: Array<{ id: string; name: string }>;
  voiceEnabled: boolean;
  mode: string;
  llmMethod: string | null;
  configuration?: FixturesConfiguration;
};

