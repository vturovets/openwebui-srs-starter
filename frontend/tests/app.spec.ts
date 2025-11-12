import { Buffer } from 'node:buffer';
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/v1/fixtures', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        airports: ['AMS'],
        destinations: ['Rome'],
        voiceEnabled: true,
        mode: 'dialog',
        llmMethod: 'rules-basic',
        availableMethods: [
          { id: 'rules-basic', type: 'rules' },
          { id: 'gpt5-default', type: 'llm' },
        ],
        defaultMethod: 'rules-basic',
        performanceTargets: {
          importP95ThresholdMs: 1000,
          importP95SampleSize: 1000,
          importP95Significance: 0.95,
        },
      }),
    });
  });

  let parseCount = 0;
  await page.route('**/v1/parse', async (route) => {
    parseCount += 1;
    if (parseCount === 1) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'failed',
          data: {},
          metadata: {
            mode: 'dialog',
            method: 'rules',
            timings: {
              languageMs: 6,
              extractionMs: 12,
              normalizationMs: 15,
              validationMs: 9,
              totalMs: 42,
            },
            recognizedSummaries: {
              airports: [],
              destinations: [],
              dates: [],
            },
            missingFields: ['to'],
          },
          clarifications: [
            { parameter: 'to', message: 'Destination required', reason: 'missing' },
          ],
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        data: { from: ['AMS'], to: ['Rome'] },
        metadata: {
          mode: 'dialog',
          method: 'rules',
          timings: {
            languageMs: 5,
            extractionMs: 11,
            normalizationMs: 8,
            validationMs: 6,
            totalMs: 30,
          },
          recognizedSummaries: {
            airports: ['AMS'],
            destinations: ['Rome'],
            dates: ['2025-11-01'],
          },
        },
      }),
    });
  });

  await page.route('**/v1/voice', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        transcript: 'Fly from Amsterdam to Rome',
        voiceEnabled: true,
        engine: 'deepgram',
        words: [],
        data: { from: ['AMS'], to: ['Rome'] },
        metadata: {
          mode: 'dialog',
          method: 'rules',
          timings: {
            languageMs: 5,
            extractionMs: 11,
            normalizationMs: 8,
            validationMs: 6,
            sttMs: 50,
            llmNetworkMs: 14,
            totalMs: 94,
          },
        },
      }),
    });
  });
});


