<script lang="ts">
  import type { HolidayResultEntry } from '../lib/types';

  export let entry: HolidayResultEntry;

  const metadata = entry.result.metadata ?? {};
  const timings = metadata.timings ?? {};
  const recognized = metadata.recognizedSummaries ?? metadata.recognized ?? {};
  const missing = metadata.missingFields ?? [];
  const invalid = metadata.invalidFields ?? [];
</script>

<article class={`result ${entry.result.status}`} data-testid="structured-result">
  <header>
    <h2>{entry.source === 'voice' ? 'Voice' : 'Text'} request</h2>
    <time datetime={entry.timestamp}>{new Date(entry.timestamp).toLocaleString()}</time>
  </header>
  <section class="status">
    <strong>Status:</strong>
    <span data-testid="status-label">{entry.result.status}</span>
    {#if entry.prompt}
      <div class="prompt" data-testid="clarification">
        <strong>Clarification needed:</strong>
        <pre>{entry.prompt}</pre>
      </div>
    {/if}
  </section>

  <section class="data">
    <h3>Structured parameters</h3>
    <ul>
      {#each Object.entries(entry.result.data || {}) as [key, value]}
        <li><strong>{key}</strong> <span>{JSON.stringify(value)}</span></li>
      {/each}
    </ul>
  </section>

  <section class="timings">
    <h3>Timings</h3>
    <table>
      <tbody>
        {#each Object.entries(timings) as [key, value]}
          <tr>
            <th>{key}</th>
            <td>{value}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>

  <section class="recognized">
    <h3>Recognised entities</h3>
    <div class="chips">
      <div>
        <strong>Airports</strong>
        <span>{(recognized.airports ?? []).join(', ') || '—'}</span>
      </div>
      <div>
        <strong>Destinations</strong>
        <span>{(recognized.destinations ?? []).join(', ') || '—'}</span>
      </div>
      <div>
        <strong>Dates</strong>
        <span>{(recognized.dates ?? []).join(', ') || '—'}</span>
      </div>
    </div>
  </section>

  {#if missing.length || invalid.length}
    <section class="issues" data-testid="issue-summary">
      <h3>Validation summary</h3>
      {#if missing.length}
        <p><strong>Missing:</strong> {missing.join(', ')}</p>
      {/if}
      {#if invalid.length}
        <p><strong>Invalid:</strong> {invalid.join(', ')}</p>
      {/if}
    </section>
  {/if}
</article>

<style>
  .result {
    background: rgba(15, 23, 42, 0.6);
    border-radius: 12px;
    padding: 1rem;
    display: grid;
    gap: 0.75rem;
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  h2 {
    margin: 0;
    font-size: 1.1rem;
  }

  time {
    font-size: 0.75rem;
    color: #94a3b8;
  }

  .status strong {
    margin-right: 0.5rem;
  }

  .status span {
    text-transform: capitalize;
  }

  .result.success {
    border: 1px solid rgba(74, 222, 128, 0.3);
  }

  .result.failed,
  .result.error {
    border: 1px solid rgba(248, 113, 113, 0.3);
  }

  .data ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.25rem;
    font-size: 0.8rem;
  }

  .data li {
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
  }

  .data strong {
    min-width: 120px;
    color: #94a3b8;
    font-weight: 600;
  }

  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.8rem;
  }

  th,
  td {
    padding: 0.25rem 0.5rem;
    text-align: left;
    border-bottom: 1px solid rgba(148, 163, 184, 0.3);
  }

  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 0.5rem;
  }

  .chips div {
    background: rgba(51, 65, 85, 0.5);
    border-radius: 8px;
    padding: 0.5rem;
  }

  .chips strong {
    display: block;
    margin-bottom: 0.25rem;
    color: #cbd5f5;
    font-size: 0.75rem;
  }

  .chips span {
    font-size: 0.8rem;
  }

  .prompt {
    background: rgba(248, 113, 113, 0.15);
    border-radius: 8px;
    padding: 0.5rem;
    margin-top: 0.5rem;
  }

  .prompt pre {
    margin: 0;
    white-space: pre-wrap;
    font-size: 0.75rem;
  }

  .issues p {
    margin: 0.25rem 0 0;
    font-size: 0.8rem;
  }
</style>

