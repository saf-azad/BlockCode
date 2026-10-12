import { defineConfig } from '@playwright/test';

// End-to-end tests drive the real app: the FastAPI engine serves the built web app.
// Run `npm run build` first, then `npm run e2e`.
//
// Three engines: most tests run Python and R on the server (fast and offline). The browser
// runtime tests (e2e/runtime.spec.ts) use one whose Pyodide and webR downloads always fail, to
// check the fallback, and one with the real downloads, which skips itself when they're blocked.
const engine = (port: number, env: Record<string, string>) => ({
  command: `cd .. && uv run blockcode serve --port ${port}`,
  url: `http://127.0.0.1:${port}/api/health`,
  reuseExistingServer: false,
  timeout: 60_000,
  env,
});

export const PORTS = { server: 8799, unreachable: 8798, browser: 8797 };

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${PORTS.server}`,
    viewport: { width: 1440, height: 900 },
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  webServer: [
    engine(PORTS.server, { BLOCKCODE_RUN_IN: 'server' }),
    engine(PORTS.unreachable, {
      BLOCKCODE_RUN_IN: 'browser',
      BLOCKCODE_PYODIDE_URL: 'http://127.0.0.1:9/pyodide.mjs',
      BLOCKCODE_WEBR_URL: 'http://127.0.0.1:9/webr.mjs',
    }),
    engine(PORTS.browser, { BLOCKCODE_RUN_IN: 'browser' }),
  ],
});
