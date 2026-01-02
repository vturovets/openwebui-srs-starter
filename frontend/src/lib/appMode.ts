export type AppMode = 'default' | 'holiday_only' | 'preferences_only';
export type ConsoleMode = 'holiday' | 'preferences';

const APP_MODES: AppMode[] = ['default', 'holiday_only', 'preferences_only'];

export function resolveAppMode(rawValue: string | undefined | null): AppMode {
  const normalized = rawValue?.trim().toLowerCase();
  // Resolve once here so components only deal with a trusted, finite set of modes.
  return APP_MODES.includes(normalized as AppMode) ? (normalized as AppMode) : 'default';
}

export function getConsoleConfig(mode: AppMode): {
  showHoliday: boolean;
  showPreferences: boolean;
  lockedMode: ConsoleMode | null;
} {
  switch (mode) {
    case 'holiday_only':
      return {
        showHoliday: true,
        showPreferences: false,
        lockedMode: 'holiday',
      };
    case 'preferences_only':
      return {
        showHoliday: false,
        showPreferences: true,
        lockedMode: 'preferences',
      };
    default:
      return {
        showHoliday: true,
        showPreferences: true,
        lockedMode: null,
      };
  }
}

export const appMode = resolveAppMode(
  (globalThis as { __APP_MODE__?: string }).__APP_MODE__ ?? (import.meta as any)?.env?.APP_MODE
);
