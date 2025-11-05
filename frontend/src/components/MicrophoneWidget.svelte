<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { HolidayResult } from '../lib/types';

  export let mode: string;
  export let handleVoiceUpload: (form: FormData) => Promise<HolidayResult & { transcript?: string }>;

  const dispatch = createEventDispatcher();

  let status: 'idle' | 'recording' | 'uploading' | 'success' | 'failed' = 'idle';
  let message = 'Use your microphone to dictate a request.';

  async function onFileChange(event: Event) {
    const target = event.target as HTMLInputElement;
    const file = target.files?.[0];
    if (!file) {
      return;
    }
    status = 'uploading';
    message = 'Uploading audio…';
    const form = new FormData();
    form.append('audio', file, file.name);

    try {
      const response = await handleVoiceUpload(form);
      status = response.status === 'success' ? 'success' : 'failed';
      message = response.status === 'success' ? 'Transcript received.' : 'Voice request failed.';
      dispatch('voiceResult', {
        transcript: response.transcript ?? '',
        response,
      });
    } catch (error) {
      status = 'failed';
      message = error instanceof Error ? error.message : 'Voice upload failed.';
    } finally {
      target.value = '';
    }
  }
</script>

<section class="voice" data-testid="microphone-widget">
  <header>
    <h2>Voice input</h2>
    <p data-testid="voice-status" class={status}>{message}</p>
  </header>
  <label class="microphone">
    <span>Upload audio</span>
    <input type="file" accept="audio/*" on:change={onFileChange} data-testid="voice-input" />
  </label>
  <p class="mode">Active mode: {mode}</p>
</section>

<style>
  .voice {
    background: rgba(15, 23, 42, 0.4);
    border-radius: 12px;
    padding: 1rem;
    display: grid;
    gap: 0.5rem;
  }

  h2 {
    margin: 0;
    font-size: 1.1rem;
  }

  p {
    margin: 0;
    font-size: 0.85rem;
  }

  .microphone {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    border: 1px dashed #38bdf8;
    border-radius: 999px;
    padding: 0.4rem 0.75rem;
    cursor: pointer;
  }

  .microphone input {
    display: none;
  }

  .mode {
    font-size: 0.75rem;
    color: #94a3b8;
  }

  .uploading {
    color: #facc15;
  }

  .success {
    color: #4ade80;
  }

  .failed {
    color: #f87171;
  }
</style>

