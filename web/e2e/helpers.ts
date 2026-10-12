import { expect, type Page } from '@playwright/test';

// Shared by the end-to-end specs: a fresh visitor with the school CSVs and a program.

export const SAMPLE = '../blockcode/data/sample';
export const DEPARTMENTS = `SELECT dept,
       AVG(grade) AS avg_grade,
       COUNT(*) AS n
FROM enrolments
JOIN courses USING (course_id)
WHERE grade > 50
GROUP BY dept
HAVING COUNT(*) >= 10
ORDER BY avg_grade DESC
LIMIT 5;`;

export async function typeCode(page: Page, text: string) {
  await page.locator('.cm-content').click();
  await page.keyboard.press('Control+A');
  await page.keyboard.insertText(text);
  await expect(page.getByText(/Blocks updated|Blocks unchanged/)).toBeVisible();
}

export async function runTable(page: Page) {
  await page.getByTestId('run').click();
  await expect(page.getByTestId('run-status')).toContainText('Ran as');
  return page.getByTestId('result').last().locator('tbody tr').evaluateAll((rows) =>
    rows.map((r) => Array.from(r.querySelectorAll('td')).slice(1).map((td) => td.textContent)));
}

export async function addFiles(page: Page, files: Parameters<ReturnType<Page['locator']>['setInputFiles']>[0], count: number) {
  await page.locator('input[type=file]').first().setInputFiles(files);
  await expect(page.locator('.table-card')).toHaveCount(count);
  await page.locator('.overlay').click(); // dismiss "Columns we found"
  await expect(page.locator('.overlay')).toHaveCount(0);
}

/** A fresh visitor: blank workspace, then the school CSVs and (optionally) a program typed as SQL. */
export async function open(page: Page, program = true) {
  await page.goto('/');
  await expect(page.getByTestId('welcome')).toBeVisible();
  await addFiles(page, ['students', 'courses', 'enrolments'].map((t) => `${SAMPLE}/${t}.csv`), 3);
  if (program) {
    await typeCode(page, DEPARTMENTS);
    await page.getByRole('button', { name: 'Tidy' }).click();
    await expect(page.locator('[data-type="join"]')).toBeVisible();
  }
}
