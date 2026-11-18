import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/demo',
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['json', { outputFile: '.demo/browser-result.json' }]],
  outputDir: '.demo/browser-output',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.2:5180',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
