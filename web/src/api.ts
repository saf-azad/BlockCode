import type { StoredTable } from './local';
import type { BlockSpec, Erd, Generated, Job, Lang, ParseResult, Program, Raw, RunResult, RuntimeConfig, TableInfo } from './types';

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error("Can't reach BlockCode right now. Check your connection and try again.");
  }
  if (!res.ok) {
    let message = res.status === 413 ? 'That is too much data to send at once.' : res.statusText || `Error ${res.status}`;
    try {
      const detail = (await res.json()).detail;
      if (typeof detail === 'string') message = detail;
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/** A run or export request: the program as JSON plus every table's CSV. */
function withData(body: unknown, tables: StoredTable[]): RequestInit {
  const form = new FormData();
  form.append('request', JSON.stringify(body));
  for (const t of tables) form.append('files', t.data, `${t.info.name}.csv`);
  return { method: 'POST', body: form };
}

export interface Health {
  ok: boolean;
  version: string;
  r: boolean;
  max_file: number;
  run_in: RuntimeConfig['run_in'];
}

export const api = {
  health: () => call<Health>('/api/health'),
  blocks: () => call<{ blocks: BlockSpec[]; step_order: string[] }>('/api/blocks'),
  inspect: (data: Blob, filename: string) => {
    const form = new FormData();
    form.append('file', data, filename);
    return call<{ table: TableInfo; notes: string[] }>('/api/tables', { method: 'POST', body: form });
  },
  generateAll: (program: Program, tables: TableInfo[], title: string) =>
    call<Record<Lang, Generated>>('/api/generate-all', json({ program, tables, title })),
  parse: (code: string, lang: Lang, tables: TableInfo[], previous: Program) =>
    call<ParseResult>('/api/parse', json({ code, lang, tables, previous })),
  erd: (tables: TableInfo[]) => call<Erd>('/api/erd', json({ tables })),
  run: (program: Program, target: Lang, tables: StoredTable[]) =>
    call<RunResult>('/api/run', withData({ program, target }, tables)),
  runtime: () => call<RuntimeConfig>('/api/runtime'),
  /** Python or R to run in this browser: the code and tidied CSVs, or why it can't run. */
  job: (program: Program, target: Lang, tables: StoredTable[]) =>
    call<{ job?: Job; result?: RunResult }>('/api/job', withData({ program, target }, tables)),
  /** Turn what a run in this browser produced into a result (friendly errors, their blocks). */
  finish: (program: Program, target: Lang, tables: TableInfo[], raw: Raw) =>
    call<RunResult>('/api/finish', json({ program, target, tables, raw })),
  export: async (program: Program, target: Lang, title: string, tables: StoredTable[]) => {
    let res: Response;
    try {
      res = await fetch('/api/export', withData({ program, target, title }, tables));
    } catch {
      throw new Error("Can't reach BlockCode right now. Check your connection and try again.");
    }
    if (!res.ok) {
      let message = res.statusText;
      try {
        message = (await res.json()).detail ?? message;
      } catch {
        /* not JSON */
      }
      throw new Error(message);
    }
    return res.blob();
  },
};
