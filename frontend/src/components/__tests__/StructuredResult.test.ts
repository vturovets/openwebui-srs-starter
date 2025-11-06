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
        data: {},
        metadata: {
          timings: {},
          recognized: {
            airports: [{ code: 'AMS', name: 'Amsterdam Schiphol' }],
            destinations: [{ id: 'italy', name: 'Italy' }],
            dates: [{ phrase: 'next week', iso: '2025-10-10' }],
          },
        },
      },
    };

    render(StructuredResult, { entry });

    expect(screen.getByText(JSON.stringify({ code: 'AMS', name: 'Amsterdam Schiphol' }))).toBeInTheDocument();
    expect(screen.getByText(JSON.stringify({ id: 'italy', name: 'Italy' }))).toBeInTheDocument();
    expect(screen.getByText(JSON.stringify({ phrase: 'next week', iso: '2025-10-10' }))).toBeInTheDocument();
    expect(screen.queryByText('[object Object]')).toBeNull();
  });
});
