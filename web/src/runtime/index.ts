// Where a run happens. SQL runs on the server (SQLite). Python and R run here in the browser
// (Pyodide, webR): the server prepares the job and explains the outcome, the browser runs it.
// If Python or R can't start in this browser, runs fall back to the server.
import { api } from '../api';
import type { StoredTable } from '../local';
import type { Lang, Program, RunResult, RuntimeConfig } from '../types';
import { RuntimeLoadError, type Status } from './errors';
import { runPython, warmPython } from './python';
import { runR, warmR } from './r';

let config: Promise<RuntimeConfig> | null = null;
const unavailable: Partial<Record<Lang, string>> = {}; // why it couldn't start, once it hasn't

function runtime(): Promise<RuntimeConfig> {
  config ??= api.runtime().catch((e) => {
    config = null;
    throw e;
  });
  return config;
}

export async function inBrowser(lang: Lang): Promise<boolean> {
  if (lang === 'sql' || unavailable[lang]) return false;
  return (await runtime().catch(() => null))?.run_in === 'browser';
}

/** Start downloading Python or R in the background, ahead of the first run. */
export async function warm(lang: Lang, code: string) {
  if (!(await inBrowser(lang))) return;
  const cfg = await runtime();
  if (lang === 'python') warmPython(cfg.pyodide);
  if (lang === 'r') warmR(cfg.webr, cfg.webr_repo, code);
}

/** Run the program, here if we can. ``notice`` hears about falling back to the server. */
export async function run(program: Program, lang: Lang, tables: StoredTable[], onStatus: Status,
  notice: (message: string) => void): Promise<RunResult> {
  if (!(await inBrowser(lang))) return api.run(program, lang, tables);
  const cfg = await runtime();
  const prepared = await api.job(program, lang, tables);
  if (!prepared.job) return prepared.result!;
  const job = prepared.job;
  try {
    const raw = lang === 'python'
      ? await runPython(job, cfg.pyodide, onStatus)
      : await runR(job, cfg.webr, cfg.webr_repo, onStatus);
    onStatus(null);
    return await api.finish(program, lang, tables.map((t) => t.info), raw);
  } catch (e) {
    if (!(e instanceof RuntimeLoadError)) throw e;
    unavailable[lang] = e.message;
    console.warn(e.message);
    notice(`${e.lang} couldn't start in your browser (a download didn't arrive), so it ran on the server instead.`);
    return api.run(program, lang, tables);
  }
}
