import { render, screen } from '@testing-library/svelte';
import StructuredResult from '../StructuredResult.svelte';
import type { HolidayResultEntry } from '../../lib/types';

describe('StructuredResult', () => {
  it('formats recognized entity objects without showing [object Object]', () => {
    const entry: HolidayResultEntry = {
      id: 'entry-1',
      source: 'text',
      input: 'Find a trip',
      prompt: '',
      timestamp: '2025-01-01T12:00:00.000Z',
      result: {
        status: 'success',
        data: {
          airports: [{ code: 'AMS', name: 'Amsterdam Schiphol' }],
          destinations: [{ id: 'italy', name: 'Italy' }],
          dates: [{ phrase: 'next week', iso: '2025-10-10' }],
        },
        metadata: {
          timings: {},
        },
      },
    };

    render(StructuredResult, { entry });

    expect(
      screen.getByText(JSON.stringify([{ code: 'AMS', name: 'Amsterdam Schiphol' }]))
    ).toBeInTheDocument();
    expect(screen.getByText(JSON.stringify([{ id: 'italy', name: 'Italy' }]))).toBeInTheDocument();
    expect(
      screen.getByText(JSON.stringify([{ phrase: 'next week', iso: '2025-10-10' }]))
    ).toBeInTheDocument();
    expect(screen.queryByText('[object Object]')).toBeNull();
  });

  it('renders expected value mismatches when provided', () => {
    const entry: HolidayResultEntry = {
      id: 'entry-2',
      source: 'text',
      input: 'Find a trip to Italy',
      prompt: '',
      timestamp: '2025-01-01T12:00:00.000Z',
      result: {
        status: 'failed',
        data: { from: ['AMS'], to: ['Italy'] },
        metadata: {
          timings: {},
          expectedValueMismatches: [
            { label: 'To', expected: 'Spain', actual: 'Italy' },
            { label: 'Duration', expected: '7 nights', actual: '' },
          ],
        },
      },
    };

    render(StructuredResult, { entry });

    const summaryHeading = screen.getByText('Expected value mismatches:');
    expect(summaryHeading).toBeInTheDocument();
    const summaryContainer = summaryHeading.closest('div');
    const normalised = summaryContainer?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    expect(normalised).toMatch(/expected “Spain” but got “\s*Italy”/);
    expect(normalised).toMatch(/expected “7 nights” but got “\s*—”/);
  });

  it('shows failed status with no-preferences message in preferences mode', () => {
    const entry: HolidayResultEntry = {
      id: 'entry-3',
      source: 'text',
      input: 'Just browsing',
      prompt: '',
      timestamp: '2025-01-01T12:00:00.000Z',
      result: {
        status: 'failed',
        filters: [],
        metadata: {
          mode: 'preferences',
          statusReason: 'no-preferences-detected',
          timings: {},
        },
      },
    };

    render(StructuredResult, { entry });

    expect(screen.getByTestId('status-label')).toHaveTextContent('failed');
    expect(
      screen.getByText('No preferences detected from your input.')
    ).toBeInTheDocument();
  });
});
