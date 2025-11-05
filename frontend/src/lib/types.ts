export type HolidayResult = {
  status: string;
  data: Record<string, unknown>;
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

export type HolidayResultEntry = {
  id: string;
  source: 'text' | 'voice';
  input: string;
  result: HolidayResult;
  prompt: string;
  timestamp: string;
};

export type Fixtures = {
  airports: string[];
  destinations: string[];
  durations?: Array<{ id: string; name: string }>;
  voiceEnabled?: boolean;
  mode?: string;
  llmMethod?: string | null;
};

