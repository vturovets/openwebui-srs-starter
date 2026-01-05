import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { vi } from 'vitest';
import MicrophoneWidget from '../MicrophoneWidget.svelte';
import type { VoiceResponse } from '../../lib/types';

describe('MicrophoneWidget', () => {
  it('includes mode in voice uploads when preferences mode is active', async () => {
    const handleVoiceUpload = vi.fn(async (form: FormData): Promise<VoiceResponse> => {
      expect(form.get('mode')).toBe('preferences');
      return {
        status: 'success',
        data: null,
        metadata: {},
        voiceEnabled: true,
        engine: null,
        words: [],
      };
    });

    render(MicrophoneWidget, {
      props: {
        mode: 'preferences',
        handleVoiceUpload,
        voiceEnabled: true,
      },
    });

    const input = screen.getByTestId('voice-input');
    const file = new File(['audio'], 'voice.wav', { type: 'audio/wav' });

    await fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(handleVoiceUpload).toHaveBeenCalledTimes(1);
    });
  });
});
