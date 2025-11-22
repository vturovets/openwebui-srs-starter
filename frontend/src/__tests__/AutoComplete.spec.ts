import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../lib/api', () => ({
  fetchSuggestions: vi.fn(),
}));

import AutoComplete from '../components/AutoComplete.svelte';
import { fetchSuggestions } from '../lib/api';

describe('AutoComplete', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(fetchSuggestions).mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('debounces suggestion requests', async () => {
    vi.mocked(fetchSuggestions).mockResolvedValue({ suggestions: {} });
    const { component } = render(AutoComplete, { query: '', baseUrl: 'http://example.test' });

    component.$set({ query: 'plan a trip to a' });
    component.$set({ query: 'plan a trip to au' });
    await vi.advanceTimersByTimeAsync(200);
    expect(fetchSuggestions).not.toHaveBeenCalled();

    component.$set({ query: 'plan a trip to aus' });
    await vi.advanceTimersByTimeAsync(350);
    expect(fetchSuggestions).toHaveBeenCalledTimes(1);
    expect(fetchSuggestions).toHaveBeenCalledWith('http://example.test', 'aus', 3);
  });

  it('cancels pending requests when the query clears', async () => {
    vi.mocked(fetchSuggestions).mockResolvedValue({ suggestions: {} });
    const { component } = render(AutoComplete, { query: '', baseUrl: 'http://example.test' });

    component.$set({ query: 'book me a trip to rom' });
    component.$set({ query: 'book me a trip' });
    await vi.advanceTimersByTimeAsync(400);

    expect(fetchSuggestions).not.toHaveBeenCalled();
  });

  it('emits the selected suggestion payload', async () => {
    vi.mocked(fetchSuggestions).mockResolvedValue({
      suggestions: {
        destinations: [{ value: 'Rome', label: 'Rome, Italy' }],
      },
    });
    const { component } = render(AutoComplete, {
      query: 'book me a trip to rom',
      baseUrl: 'http://example.test',
    });
    const handler = vi.fn();
    component.$on('selectSuggestion', handler);

    await vi.advanceTimersByTimeAsync(400);
    const option = await screen.findByRole('button', { name: /rome/i });
    await fireEvent.click(option);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0].detail).toEqual({
      field: 'destinations',
      value: { value: 'Rome', label: 'Rome, Italy' },
    });
  });

  it('ignores destination fragments longer than three characters', async () => {
    vi.mocked(fetchSuggestions).mockResolvedValue({ suggestions: {} });
    const { component } = render(AutoComplete, { query: '', baseUrl: 'http://example.test' });

    component.$set({ query: 'Find me a trip from Amsterdam to Austria' });
    await vi.advanceTimersByTimeAsync(400);

    expect(fetchSuggestions).not.toHaveBeenCalled();
  });
});
