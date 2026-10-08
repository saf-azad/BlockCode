import type { Erd, Generated, Lang, ParseResult, Program, Project, RunResult, TableInfo, BlockSpec } from './types';

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let message = res.statusText;
    try {
      message = (await res.json()).detail ?? message;
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

const p = (project: string) => `/api/projects/${encodeURIComponent(project)}`;

export const api = {
  blocks: () => call<{ blocks: BlockSpec[]; step_order: string[] }>('/api/blocks'),
  project: (name: string) => call<Project>(p(name)),
  saveProgram: (name: string, program: Program) =>
    call<{ ok: boolean }>(`${p(name)}/program`, { ...json(program), method: 'PUT' }),
  generateAll: (name: string, program: Program) =>
    call<Record<Lang, Generated>>(`${p(name)}/generate-all`, json({ program, target: 'sql' })),
  run: (name: string, program: Program, target: Lang) =>
    call<RunResult>(`${p(name)}/run`, json({ program, target })),
  parse: (name: string, code: string, lang: Lang, previous: Program) =>
    call<ParseResult>(`${p(name)}/parse`, json({ code, lang, previous })),
  upload: async (name: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return call<{ table: TableInfo }>(`${p(name)}/data`, { method: 'POST', body: form });
  },
  erd: (name: string) => call<Erd>(`${p(name)}/erd`),
  examples: () => call<{ examples: { name: string; title: string }[] }>('/api/examples'),
  example: (name: string) => call<Program>(`/api/examples/${encodeURIComponent(name)}`),
  export: async (name: string, program: Program, target: Lang) => {
    const res = await fetch(`${p(name)}/export`, json({ program, target }));
    if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
    return res.blob();
  },
};
