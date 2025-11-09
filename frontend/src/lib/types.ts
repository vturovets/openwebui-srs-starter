// NOTE: "Language Detection" appears twice to satisfy the reporting template used by
// analysts. The first column records the detected ISO language code while the second
// repeats the heading but stores the numeric confidence score for that detection.
export const CSV_LOG_FIELDS = [
  'Timestamp',
  'User Input',
  'Request Type',
  'Interaction Mode',
  'Processing Method',
  'Pipeline Status',
  'Language Detection',
  'Language Detection',
  'Processing Time (ms)',
  'LLM Network (ms)',
  'LLM Provider',
  'LLM Prompt Id',
  'LLM Request Id',
  'LLM Response Id',
  'Threshold Breached',
  'Missing Fields',
  'Invalid Fields',
  'Transcript',
  'Prompt JSON',
  'Output JSON',
  'Session Id',
  'Dialog Status',
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

