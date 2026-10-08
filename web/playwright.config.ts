import { defineConfig } from '@playwright/test';

// End-to-end tests drive the real app: the FastAPI engine serves the built web app.
// Run `npm run build` first, then `npm run e2e`.
// Python and R run in the browser, downloading Pyodide and webR (and pandas, ggplot2, ...) on
// their first run: allow for that. BLOCKCODE_RUN_IN=server runs them on the server instead
// (where those downloads are blocked).
export default defineConfig({
  testDir: './e2e',
  timeout: 240_000,
  expect: { timeout: 90_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:8799',
    viewport: { width: 1440, height: 900 },
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  webServer: {
    command: 'rm -rf ../.e2e-projects && cd .. && uv run blockcode serve --port 8799 -d .e2e-projects',
    url: 'http://127.0.0.1:8799/api/health',
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
