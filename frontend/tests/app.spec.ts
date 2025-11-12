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

test('dialog loop renders clarification then success and csv download remains available', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('fixtures-loaded')).toBeVisible();

  await page.getByTestId('query-input').fill('Missing destination');
  await page.getByTestId('submit-button').click();
  await expect(page.getByTestId('clarification')).toBeVisible();

  await page.getByTestId('query-input').fill('Trip to Rome');
  await page.getByTestId('submit-button').click();
  await expect(page.getByTestId('structured-result')).toBeVisible();
  await expect(page.getByTestId('status-label')).toHaveText('success');

  await page.getByTestId('export-button').click();
  await expect(page.getByTestId('csv-preview')).toContainText('Timestamp,Source,Status');
});

test('voice upload routes through parse flow and updates status indicators', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('fixtures-loaded')).toBeVisible();

  const fileChooserPromise = page.waitForEvent('filechooser');
  await page.getByTestId('voice-input').click();
  const chooser = await fileChooserPromise;
  await chooser.setFiles({ name: 'voice.wav', mimeType: 'audio/wav', buffer: Buffer.from('voice') });

  await expect(page.getByTestId('voice-status')).toContainText('Transcript received');
  await expect(page.getByTestId('structured-result')).toBeVisible();
  await expect(page.locator('[data-testid="structured-result"] pre').first()).toHaveText(
    'Fly from Amsterdam to Rome'
  );
});

test('import summary honours performance targets and exposes inference', async ({ page }) => {
  await page.unroute('**/v1/fixtures');
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
          importP95ThresholdMs: 2000,
          importP95SampleSize: 2,
          importP95Significance: 0.9,
        },
      }),
    });
  });

  await page.unroute('**/v1/parse');
  const timings = [500, 600, 700];
  await page.route('**/v1/parse', async (route) => {
    const totalMs = timings.shift() ?? 700;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        data: {},
        metadata: {
          mode: 'dialog',
          method: 'rules-basic',
          timings: {
            totalMs,
          },
        },
        clarifications: [],
      }),
    });
  });

  await page.goto('/');
  await expect(page.getByTestId('fixtures-loaded')).toBeVisible();

  const fileChooserPromise = page.waitForEvent('filechooser');
  await page.getByTestId('import-button').click();
  const chooser = await fileChooserPromise;
  const csvContent = '"User input"\n"Trip one"\n"Trip two"\n"Trip three"\n';
  await chooser.setFiles({ name: 'batch.csv', mimeType: 'text/csv', buffer: Buffer.from(csvContent) });

  await expect(page.getByTestId('performance-summary')).toBeVisible();
  await expect(page.getByTestId('performance-threshold')).toHaveText('2000 ms');
  await expect(page.getByTestId('performance-inference')).toHaveText('Meets target');
});

