<script lang="ts">
  import { createEventDispatcher, onDestroy, onMount } from 'svelte';
  import type { HolidayResult } from '../lib/types';

  export let mode: string;
  export let handleVoiceUpload: (form: FormData) => Promise<HolidayResult & { transcript?: string }>;
  export let voiceEnabled = true;

  const dispatch = createEventDispatcher();

  type WidgetStatus =
    | 'idle'
    | 'requesting'
    | 'recording'
    | 'uploading'
    | 'success'
    | 'failed'
    | 'disabled';

  let status: WidgetStatus = 'idle';
  const DISABLED_MESSAGE = 'Voice input is disabled for this environment.';
  let message = 'Use your microphone to dictate a request.';
  let recordingSupported = false;
  let mediaRecorder: MediaRecorder | null = null;
  let mediaStream: MediaStream | null = null;
  let recordedChunks: BlobPart[] = [];
  let resetTimer: ReturnType<typeof setTimeout> | null = null;

  function idleMessage(): string {
    if (!voiceEnabled) {
      return DISABLED_MESSAGE;
    }
    return recordingSupported
      ? 'Use your microphone to dictate a request.'
      : 'Upload an audio file to submit a voice request.';
  }

  function clearResetTimer() {
    if (resetTimer) {
      clearTimeout(resetTimer);
      resetTimer = null;
    }
  }

  function stopStream() {
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
      mediaStream = null;
    }
  }

  onMount(() => {
    recordingSupported =
      typeof window !== 'undefined' &&
      typeof navigator !== 'undefined' &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof MediaRecorder !== 'undefined';

    message = idleMessage();
  });

  onDestroy(() => {
    clearResetTimer();
    stopStream();
    if (mediaRecorder) {
      mediaRecorder.ondataavailable = null;
      mediaRecorder.onstop = null;
      mediaRecorder = null;
    }
  });

  async function submitForm(form: FormData) {
    if (!voiceEnabled) {
      status = 'disabled';
      message = DISABLED_MESSAGE;
      return null;
    }
    clearResetTimer();
    status = 'uploading';
    message = 'Uploading audio…';
    try {
      const response = await handleVoiceUpload(form);
      const transcript = response.transcript ?? '';
      status = response.status === 'success' ? 'success' : 'failed';
      message =
        response.status === 'success' ? 'Transcript received.' : 'Voice request failed.';
      dispatch('voiceResult', {
        transcript,
        response,
      });
      if (status === 'success') {
        resetTimer = setTimeout(() => {
          status = 'idle';
          message = idleMessage();
        }, 2500);
      }
      return response;
    } catch (error) {
      status = 'failed';
      message = error instanceof Error ? error.message : 'Voice upload failed.';
      return null;
    }
  }

  async function startRecording() {
    if (
      !voiceEnabled ||
      !recordingSupported ||
      status === 'recording' ||
      status === 'uploading' ||
      status === 'requesting'
    ) {
      return;
    }
    status = 'requesting';
    message = 'Requesting microphone access…';

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(mediaStream);
      mediaRecorder = recorder;
      recordedChunks = [];

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          recordedChunks.push(event.data);
        }
      };

      recorder.onstop = async () => {
        stopStream();
        const chunks = recordedChunks;
        recordedChunks = [];
        if (!voiceEnabled) {
          status = 'disabled';
          message = DISABLED_MESSAGE;
          mediaRecorder = null;
          return;
        }
        if (!chunks.length) {
          status = 'failed';
          message = 'No audio was captured.';
          mediaRecorder = null;
          return;
        }
        const mimeType = recorder.mimeType || 'audio/webm';
        const blob = new Blob(chunks, { type: mimeType });
        const extension = mimeType.split('/')[1]?.split(';')[0] || 'webm';
        const form = new FormData();
        form.append('audio', blob, `recording.${extension}`);
        await submitForm(form);
        mediaRecorder = null;
      };

      recorder.start();
      status = 'recording';
      message = 'Recording… tap to stop.';
    } catch (error) {
      stopStream();
      mediaRecorder = null;
      status = 'failed';
      message =
        error instanceof Error && error.message
          ? error.message
          : 'Unable to access the microphone.';
    }
  }

  function stopRecording() {
    if (mediaRecorder && status === 'recording') {
      status = 'uploading';
      message = 'Processing audio…';
      mediaRecorder.stop();
    }
  }

  function toggleRecording() {
    if (!voiceEnabled) {
      status = 'disabled';
      message = DISABLED_MESSAGE;
      return;
    }
    if (status === 'recording') {
      stopRecording();
    } else {
      startRecording();
    }
  }

  async function onFileChange(event: Event) {
    const target = event.target as HTMLInputElement;
    const file = target.files?.[0];
    if (!voiceEnabled) {
      status = 'disabled';
      message = DISABLED_MESSAGE;
      if (target) {
        target.value = '';
      }
      return;
    }
    if (!file) {
      return;
    }
    const form = new FormData();
    form.append('audio', file, file.name);
    try {
      await submitForm(form);
    } finally {
      target.value = '';
    }
  }
  $: if (!voiceEnabled) {
    clearResetTimer();
    stopStream();
    recordedChunks = [];
    if (mediaRecorder) {
      try {
        mediaRecorder.ondataavailable = null;
        mediaRecorder.onstop = null;
        if (mediaRecorder.state !== 'inactive') {
          mediaRecorder.stop();
        }
      } catch {
        // ignore errors during forced stop
      }
      mediaRecorder = null;
    }
    status = 'disabled';
    message = DISABLED_MESSAGE;
  } else if (status === 'disabled') {
    status = 'idle';
    message = idleMessage();
  } else if (status === 'idle') {
    message = idleMessage();
  }
</script>

<section class="voice" data-testid="microphone-widget">
  <header>
    <h2>Voice input</h2>
    <p data-testid="voice-status" class={status}>{message}</p>
  </header>

  <div class="controls">
    <button
      type="button"
      class="record-button"
      class:recording={status === 'recording'}
      on:click={toggleRecording}
      disabled={!voiceEnabled || !recordingSupported || status === 'uploading' || status === 'requesting'}
      aria-pressed={status === 'recording'}
      data-testid="record-button"
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        focusable="false"
        class="icon"
      >
        <path
          d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z"
          fill="currentColor"
        />
      </svg>
      <span>{status === 'recording' ? 'Stop recording' : 'Record voice'}</span>
    </button>

    <label class="upload" class:disabled={!voiceEnabled}>
      <span>Upload audio</span>
      <input
        type="file"
        accept="audio/*"
        on:change={onFileChange}
        data-testid="voice-input"
        disabled={!voiceEnabled}
      />
    </label>
  </div>

  <p class="mode">Active mode: {mode}</p>
</section>

<style>
  .voice {
    background: rgba(15, 23, 42, 0.4);
    border-radius: 12px;
    padding: 1rem;
    display: grid;
    gap: 0.75rem;
  }

  h2 {
    margin: 0;
    font-size: 1.1rem;
  }

  p {
    margin: 0;
    font-size: 0.85rem;
  }

  .controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    align-items: center;
  }

  .record-button {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    border: none;
    border-radius: 999px;
    padding: 0.55rem 1rem;
    cursor: pointer;
    background: #f97316;
    color: #0f172a;
    font: inherit;
    transition: background 0.2s ease, box-shadow 0.2s ease;
  }

  .record-button:hover:enabled {
    background: #fb923c;
  }

  .record-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .record-button.recording {
    background: #ef4444;
    color: #f8fafc;
    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4);
    animation: pulse 1.5s ease infinite;
  }

  .record-button .icon {
    width: 1.1rem;
    height: 1.1rem;
  }

  @keyframes pulse {
    0% {
      box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4);
    }
    70% {
      box-shadow: 0 0 0 8px rgba(239, 68, 68, 0);
    }
    100% {
      box-shadow: 0 0 0 0 rgba(239, 68, 68, 0);
    }
  }

  .upload {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    border: 1px dashed #38bdf8;
    border-radius: 999px;
    padding: 0.45rem 0.85rem;
    cursor: pointer;
  }

  .upload input {
    display: none;
  }

  .upload.disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .mode {
    font-size: 0.75rem;
    color: #94a3b8;
  }

  .requesting,
  .uploading {
    color: #facc15;
  }

  .success {
    color: #4ade80;
  }

  .failed {
    color: #f87171;
  }

  .disabled {
    color: #94a3b8;
  }
</style>

