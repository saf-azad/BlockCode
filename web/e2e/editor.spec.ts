import { expect, test, type Page } from '@playwright/test';

async function blockIds(page: Page) {
  return page.locator('[data-block]').evaluateAll((els) => els.map((e) => e.getAttribute('data-block')));
}

async function code(page: Page) {
  return (await page.locator('.cm-content').innerText()).replace(/ /g, ' ');
}

async function typeCode(page: Page, text: string) {
  await page.locator('.cm-content').click();
  await page.keyboard.press('Control+A');
  await page.keyboard.insertText(text);
  await expect(page.getByText(/Blocks updated|Blocks unchanged/)).toBeVisible();
}

async function runTable(page: Page) {
  await page.getByTestId('run').click();
  await expect(page.getByTestId('run-status')).toContainText('Ran as');
  return page.getByTestId('result').last().locator('tbody tr').evaluateAll((rows) =>
    rows.map((r) => Array.from(r.querySelectorAll('td')).slice(1).map((td) => td.textContent)));
}

let n = 0;
async function open(page: Page) {
  n += 1;
  await page.goto(`/?project=e2e-${Date.now().toString(36)}-${n}`);
  await expect(page.locator('[data-type="from"]').first()).toBeVisible();
}

test('drop a CSV, build a stack, flip languages, run both', async ({ page }) => {
  await open(page);
  // start again from an empty workspace
  await page.getByRole('button', { name: 'Examples ▾' }).click();
  await page.getByRole('menuitem', { name: 'Empty workspace' }).click();
  await expect(page.locator('[data-block]')).toHaveCount(0);

  // drop a CSV: it is loaded as a table and shown with its column types
  await page.locator('input[type=file]').setInputFiles('../tests/fixtures/pets.csv');
  await expect(page.getByText('Columns we found')).toBeVisible();
  await expect(page.locator('.table-card', { hasText: 'pets' })).toContainText('2 empty values');

  // FROM pets → WHERE → GROUP BY, by clicking the palette
  await page.getByRole('button', { name: 'FROM', exact: true }).click();
  await page.locator('[data-type="from"] select').first().selectOption('pets');
  await page.getByRole('button', { name: 'WHERE', exact: true }).click();
  await page.locator('[data-type="where"] input').first().fill('2');
  await page.getByRole('button', { name: 'GROUP BY', exact: true }).click();
  await expect(page.locator('[data-type="group"]')).toBeVisible();
  await expect.poll(() => code(page)).toContain('GROUP BY');
  const ids = await blockIds(page);

  // the language toggle changes the code, never the blocks
  await page.getByRole('tab', { name: 'Python' }).click();
  await expect.poll(() => code(page)).toContain('groupby(');
  await page.getByRole('tab', { name: 'R', exact: true }).click();
  await expect.poll(() => code(page)).toContain('group_by(');
  expect(await blockIds(page)).toEqual(ids);

  // both targets give the same table
  await page.getByRole('tab', { name: 'SQL' }).click();
  const sqlRows = await runTable(page);
  await page.getByRole('tab', { name: 'Code' }).click();
  await page.getByRole('tab', { name: 'Python' }).click();
  const pyRows = await runTable(page);
  expect(sqlRows.length).toBeGreaterThan(0);
  expect([...pyRows].sort()).toEqual([...sqlRows].sort());
});

test('typing code builds blocks', async ({ page }) => {
  await open(page);
  await typeCode(page, "SELECT name, year\nFROM students\nWHERE year >= 12\nORDER BY name\nLIMIT 3;");
  await expect(page.locator('[data-type="limit"] input')).toHaveValue('3');
  await expect(page.locator('[data-type="where"]')).toHaveCount(1);
  await expect(page.locator('[data-type="from"] label').first()).toContainText('students');

  // a pandas snippet rebuilds the stack
  await page.getByRole('tab', { name: 'Python' }).click();
  await typeCode(page, 'import pandas as pd\nenrolments = pd.read_csv("data/enrolments.csv")\n' +
    'out = enrolments.groupby("term", as_index=False).agg(n=("grade", "count"))\n');
  await expect(page.locator('[data-type="group"]')).toBeVisible();
  await expect(page.locator('[data-type="limit"]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Tidy' }).click();
  await expect.poll(() => code(page)).toContain('dropna=False');

  // SQL that can't be blocks leaves the blocks alone and says why
  await page.getByRole('tab', { name: 'SQL' }).click();
  await typeCode(page, 'SELECT * FROM (SELECT * FROM students)');
  await expect(page.getByText(/Blocks unchanged: Not a block yet/)).toBeVisible();
  await expect(page.locator('[data-type="group"]')).toBeVisible();
});

test('for each turns SQL off; errors link back to their block', async ({ page }) => {
  await open(page);
  await page.locator('.workspace').click({ position: { x: 700, y: 600 } });
  await page.getByRole('button', { name: 'For each', exact: true }).click();
  await expect(page.locator('[data-type="foreach"]')).toBeVisible();
  await expect(page.getByRole('tab', { name: 'SQL' })).toHaveClass(/off/);
  await expect(page.getByText(/SQL is off/)).toBeVisible();
  await page.getByRole('tab', { name: /Problems/ }).click();
  await expect(page.getByText('for each has no SQL equivalent.')).toBeVisible();

  // a NameError: the error card points at the print block
  await page.getByRole('tab', { name: 'Code' }).click();
  await typeCode(page, 'import pandas as pd\nenrolments = pd.read_csv("data/enrolments.csv")\nout = enrolments.head(2)\n' +
    'for row in out.itertuples():\n    print(best, row.grade)\n');
  await expect(page.locator('[data-type="print"]')).toBeVisible();
  await page.getByTestId('run').click();
  await expect(page.getByTestId('run-error')).toContainText('NameError');
  await expect(page.getByTestId('run-error')).toContainText('best is used before it has a value');
  await page.getByTestId('run-error').click();
  await expect(page.locator('[data-type="print"]')).toHaveClass(/focus/);
});

test('plots detach in SQL and draw in Python; export all three', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Plot', exact: true }).click();
  const plot = page.locator('[data-type="plot"]');
  await expect(plot).toHaveClass(/detached/);
  await expect(page.getByRole('tab', { name: 'SQL' })).not.toHaveClass(/off/);

  for (const [tab, ext] of [['SQL', '.sql'], ['Python', '.py'], ['R', '.qmd']] as const) {
    await page.getByRole('tab', { name: tab, exact: true }).click();
    const download = page.waitForEvent('download');
    await page.getByTestId('export').click();
    expect((await download).suggestedFilename()).toMatch(/\.zip$/);
    await expect(page.getByTestId('export')).toContainText(ext);
  }

  await page.getByRole('tab', { name: 'Python' }).click();
  await expect(plot).not.toHaveClass(/detached/);
  await page.getByTestId('run').click();
  await expect(page.getByTestId('run-status')).toContainText('1 plot');
  await page.getByRole('tab', { name: 'Plot' }).click();
  await expect(page.locator('.plotcard img')).toBeVisible();
});

test('hovering a block shows it in all three languages and its animation', async ({ page }) => {
  await open(page);
  await page.locator('[data-type="join"]').hover({ position: { x: 40, y: 20 } });
  const bar = page.getByTestId('tribar');
  await expect(bar.locator('[data-lang="sql"]')).toHaveText('JOIN courses USING (course_id)');
  await expect(bar.locator('[data-lang="python"]')).toContainText('merge(courses, on="course_id")');
  await expect(bar.locator('[data-lang="r"]')).toContainText('inner_join(courses, by = "course_id")');
  await expect(page.locator('.explainer svg[data-scene="join"]')).toBeVisible();
  await expect(page.locator('.cm-line.hl')).toHaveCount(1);
});

async function drag(page: Page, from: ReturnType<Page['locator']>, to: ReturnType<Page['locator']>, dy = 0) {
  // keep the target away from the workspace edges, where dragging auto-scrolls
  await to.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await from.scrollIntoViewIfNeeded();
  const a = (await from.boundingBox())!;
  const b = (await to.boundingBox())!;
  await page.mouse.move(a.x + 20, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(a.x + 40, a.y + a.height / 2 + 10, { steps: 5 });
  await page.mouse.move(b.x + 60, b.y + b.height / 2 + dy, { steps: 12 });
  await page.waitForTimeout(150);
  await page.mouse.up();
}

test('drag and drop: palette to stack, table to workspace, block into a loop', async ({ page }) => {
  await open(page);
  // drag WHERE from the palette onto the gap under the From block
  await expect(page.locator('[data-type="where"]')).toHaveCount(1);
  await drag(page, page.getByRole('button', { name: 'WHERE', exact: true }), page.locator('[data-type="from"]'), 28);
  await expect(page.locator('[data-type="where"]')).toHaveCount(2);

  // drag the students table onto the end of the program: a new stack starts
  await drag(page, page.locator('.table-card', { hasText: 'students' }), page.locator('[data-type="limit"]'), 60);
  await expect(page.locator('[data-type="from"]')).toHaveCount(2);
  await expect(page.locator('[data-type="from"] label', { hasText: 'students' }).first()).toBeVisible();

  // a For each, then drag Print into its body
  await page.locator('.workspace').click({ position: { x: 700, y: 600 } });
  await page.getByRole('button', { name: 'For each', exact: true }).click();
  await page.locator('.workspace').click({ position: { x: 700, y: 600 } });
  await drag(page, page.getByRole('button', { name: 'Print', exact: true }), page.locator('[data-type="foreach"] .drop-end'), 0);
  await expect(page.locator('[data-type="foreach"] [data-type="print"]')).toBeVisible();
});
