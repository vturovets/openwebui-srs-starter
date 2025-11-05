import '@testing-library/jest-dom/vitest';

// Provide a deterministic base URL for tests.
Object.defineProperty(globalThis, '__HOLIDAY_API__', {
  configurable: true,
  writable: true,
  value: 'https://example.test',
});

