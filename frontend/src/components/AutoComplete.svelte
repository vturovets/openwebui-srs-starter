<script lang="ts">
  import { createEventDispatcher, onDestroy } from 'svelte';
  import { fetchSuggestions } from '../lib/api';
  import type {
    DateSuggestion,
    SuggestionValue,
    SuggestionsByField,
  } from '../lib/types';

  const DEBOUNCE_MS = 300;

  type SuggestionField = keyof SuggestionsByField;

  export let query = '';
  export let baseUrl = '';
  export let limit = 3;
  export let disabled = false;

  const dispatch = createEventDispatcher<{ selectSuggestion: { field: SuggestionField; value: unknown } }>();

  let suggestions: SuggestionsByField | null = null;
  let loading = false;
  let errorMessage = '';
  let debounceId: ReturnType<typeof setTimeout> | null = null;
  let activeRequestId = 0;
  let destinationSearch: string | null = null;

  const DESTINATION_TRIGGER = /(?:^|\s)to\s+([^\s]*)\s*$/i;

  const sections: Array<{ field: SuggestionField; label: string }> = [
    { field: 'destinations', label: 'Destinations' },
    { field: 'departureDates', label: 'Dates' },
    { field: 'durations', label: 'Duration' },
    { field: 'party', label: 'Party' },
    { field: 'rooms', label: 'Rooms' },
    { field: 'from', label: 'From' },
  ];

  function resolveDestinationSearch(input: string): string | null {
    if (!input) {
      return null;
    }

    const match = DESTINATION_TRIGGER.exec(input);
    if (!match) {
      return null;
    }

    const term = (match[1] ?? '').trim();
    if (term.length > 3) {
      return null;
    }

    return term;
  }

  function clearTimer() {
    if (debounceId) {
      clearTimeout(debounceId);
      debounceId = null;
    }
  }

  async function requestSuggestions(search: string, currentLimit: number) {
    const requestId = ++activeRequestId;
    loading = true;
    errorMessage = '';
    try {
      const response = await fetchSuggestions(baseUrl, search, currentLimit);
      if (requestId === activeRequestId) {
        const data = response?.suggestions ?? {};
        const hasEntries = sections.some(({ field }) => (data?.[field]?.length ?? 0) > 0);
        suggestions = hasEntries ? (data as SuggestionsByField) : null;
      }
    } catch (error) {
      if (requestId === activeRequestId) {
        const message = error instanceof Error ? error.message : 'Unable to load suggestions';
        errorMessage = message;
        suggestions = null;
      }
    } finally {
      if (requestId === activeRequestId) {
        loading = false;
      }
    }
  }

  function scheduleFetch(search: string, currentLimit: number) {
    clearTimer();
    debounceId = setTimeout(() => {
      debounceId = null;
      requestSuggestions(search, currentLimit);
    }, DEBOUNCE_MS);
  }

  function cancelRequests() {
    clearTimer();
    activeRequestId += 1;
    loading = false;
  }

  function handleSelect(field: SuggestionField, value: unknown) {
    dispatch('selectSuggestion', { field, value });
  }

  function formatDateSuggestion(suggestion: DateSuggestion) {
    const primary = `${suggestion.start} – ${suggestion.end}`;
    const meta = suggestion.label || suggestion.source;
    return { primary, meta };
  }

  function formatPartySuggestion(value: SuggestionValue<{ adults: number; nonAdults: number }>) {
    const { adults, nonAdults } = value.value;
    const parts: string[] = [];
    parts.push(`${adults} adult${adults === 1 ? '' : 's'}`);
    if (typeof nonAdults === 'number' && nonAdults > 0) {
      parts.push(`${nonAdults} child${nonAdults === 1 ? '' : 'ren'}`);
    }
    const primary = parts.join(', ');
    const meta = value.label || value.source;
    return { primary, meta };
  }

  function formatDefaultSuggestion(value: SuggestionValue) {
    const rawValue = String(value.value);
    return {
      primary: value.label || rawValue,
      meta: value.label && value.label !== rawValue ? rawValue : value.source,
    };
  }

  function describeSuggestion(field: SuggestionField, suggestion: unknown) {
    if (!suggestion) {
      return { primary: '', meta: '' };
    }

    if (field === 'departureDates') {
      return formatDateSuggestion(suggestion as DateSuggestion);
    }

    if (field === 'party') {
      return formatPartySuggestion(suggestion as SuggestionValue<{ adults: number; nonAdults: number }>);
    }

    return formatDefaultSuggestion(suggestion as SuggestionValue);
  }

  $: destinationSearch = resolveDestinationSearch(query);

  $: {
    const resolvedBase = baseUrl;
    const numericLimit = Number.isFinite(limit) ? Math.floor(limit) : 3;
    const safeLimit = numericLimit > 0 ? numericLimit : 3;
    if (disabled || !resolvedBase || destinationSearch === null) {
      cancelRequests();
      suggestions = null;
      errorMessage = '';
    } else {
      scheduleFetch(destinationSearch, safeLimit);
    }
  }

  const shouldRender = () => !disabled && destinationSearch !== null;

  onDestroy(() => {
    cancelRequests();
  });
</script>

{#if shouldRender()}
  <div class="autocomplete" data-testid="autocomplete">
    {#if loading}
      <p class="status">Looking for suggestions…</p>
    {:else if errorMessage}
      <p class="status error">{errorMessage}</p>
    {:else if suggestions}
      {#each sections as { field, label }}
        {#if suggestions?.[field]?.length}
          <section class="group">
            <h3>{label}</h3>
            <ul>
              {#each suggestions[field] as item (JSON.stringify(item))}
                {#if item}
                  {@const description = describeSuggestion(field, item)}
                  <li>
                    <button type="button" on:click={() => handleSelect(field, item)}>
                      {#if description.primary}
                        <span class="primary">{description.primary}</span>
                      {/if}
                      {#if description.meta}
                        <span class="meta">{description.meta}</span>
                      {/if}
                    </button>
                  </li>
                {/if}
              {/each}
            </ul>
          </section>
        {/if}
      {/each}
    {:else}
      <p class="status">No suggestions yet</p>
    {/if}
  </div>
{/if}

<style>
  .autocomplete {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem;
    border-radius: 12px;
    background: rgba(15, 23, 42, 0.7);
    border: 1px solid #1e293b;
  }

  .group {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .group h3 {
    margin: 0;
    font-size: 0.8rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #94a3b8;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  li button {
    width: 100%;
    text-align: left;
    border-radius: 10px;
    border: 1px solid rgba(148, 163, 184, 0.2);
    background: rgba(30, 41, 59, 0.65);
    padding: 0.5rem 0.75rem;
    color: inherit;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }

  li button:hover {
    border-color: #38bdf8;
    background: rgba(56, 189, 248, 0.1);
  }

  .primary {
    font-weight: 600;
  }

  .meta {
    font-size: 0.85rem;
    color: #94a3b8;
  }

  .status {
    margin: 0;
    font-size: 0.85rem;
    color: #94a3b8;
  }

  .status.error {
    color: #fca5a5;
  }
</style>
