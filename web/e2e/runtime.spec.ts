import { expect, test, type Page } from '@playwright/test';
import { PORTS } from '../playwright.config';
import { open } from './helpers';

// Python and R run in the visitor's browser (Pyodide, webR). These check where a run happens
// by watching which API calls it makes: /api/job + /api/finish for a run here, /api/run for
// one on the server.
function apiCalls(page: Page) {
  const calls: string[] = [];
  page.on('request', (r) => {
    const m = new URL(r.url()).pathname.match(/^\/api\/(run|job|finish)$/);
    if (m) calls.push(m[1]);
  });
  return calls;
}

async function runAs(page: Page, lang: 'Python' | 'R') {
  await page.getByRole('tab', { name: 'Code' }).click();
  await page.getByRole('tab', { name: lang, exact: true }).click();
  await page.getByTestId('run').click();
}

test.describe('when Python and R can\'t start in the browser', () => {
  test.use({ baseURL: `http://127.0.0.1:${PORTS.unreachable}` });

  test('runs fall back to the server and say so', async ({ page }) => {
    const calls = apiCalls(page);
    await open(page);
    await runAs(page, 'Python');
    await expect(page.getByRole('status').filter({ hasText: "Python couldn't start in your browser" })).toBeVisible();
    await expect(page.getByTestId('run-status')).toContainText('Ran as Python · 5 rows');
    expect(calls).toEqual(['job', 'run']);

    // once Python is known not to start here, later runs go straight to the server
    calls.length = 0;
    await page.getByTestId('run').click();
    await expect(page.getByTestId('run-status')).toContainText('Ran as Python · 5 rows');
    expect(calls).toEqual(['run']);
  });
});

test.describe('in a browser that can download Pyodide and webR', () => {
  test.use({ baseURL: `http://127.0.0.1:${PORTS.browser}` });

  test('Python and R run in the browser, plots and all', async ({ page, request }) => {
    // the first run downloads Python or R, then pandas or dplyr and ggplot2
    test.setTimeout(400_000);
    const cfg = await (await request.get('/api/runtime')).json();
    const reachable = await Promise.all([cfg.pyodide, cfg.webr].map((u: string) =>
      request.head(u, { timeout: 15_000 }).then((r) => r.ok(), () => false)));
    test.skip(!reachable.every(Boolean), 'Pyodide or webR can\'t be downloaded from here');

    const calls = apiCalls(page);
    await open(page);
    for (const lang of ['Python', 'R'] as const) {
      calls.length = 0;
      await page.getByRole('tab', { name: 'Code' }).click();
      await page.getByRole('tab', { name: lang, exact: true }).click();
      await page.getByRole('button', { name: /^(plot|ggplot)$/i }).click();
      await page.getByTestId('run').click();
      await expect(page.getByTestId('run-status')).toContainText(`Ran as ${lang} · 5 rows · 1 plot`, { timeout: 180_000 });
      expect(calls).toEqual(['job', 'finish']);
      await expect(page.getByTestId('result').first()).toContainText('Mathematics');
      await page.locator('[data-type="plot"] button[aria-label^="Remove"]').first().click();
      await expect(page.locator('[data-type="plot"]')).toHaveCount(0);
    }
  });
});
