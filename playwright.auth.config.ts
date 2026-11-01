import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  globalSetup: './tests/support/session-setup.ts',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 2,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  outputDir: 'test-results/auth',
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report/auth' }],
    ['json', { outputFile: 'test-results/auth-results.json' }],
  ],
  use: { trace: 'off', screenshot: 'off', video: 'off' },
  projects: [
    { name: 'session-api', testDir: './tests/auth-api', use: { baseURL: 'http://127.0.0.1:8002' } },
    {
      name: 'session-browser',
      testDir: './tests/auth-browser',
      use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:4175' },
    },
  ],
  webServer: {
    env: { VITE_API_BASE_URL: 'http://127.0.0.1:8002' },
    command: 'npm run test:serve:frontend',
    url: 'http://127.0.0.1:4175',
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
