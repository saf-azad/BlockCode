// Mirrors blockcode/ir.py and the API responses.

export type Lang = 'sql' | 'python' | 'r';
export const LANGS: Lang[] = ['sql', 'python', 'r'];
export const LANG_LABEL: Record<Lang, string> = { sql: 'SQL', python: 'Python', r: 'R' };

export interface Block {
  id: string;
  type: string;
  fields: Record<string, any>;
  inputs: Record<string, Block>;
  stacks: Record<string, Block[]>;
}

export interface Program {
  blocks: Block[];
}

export interface ColumnInfo {
  name: string;
  type: string;
  empty: number;
}

export interface TableInfo {
  name: string;
  file: string;
  rows: number;
  columns: ColumnInfo[];
}

export interface Project {
  name: string;
  title: string;
  tables: TableInfo[];
  program: Program;
}

export interface Diagnostic {
  severity: 'error' | 'warning' | 'sql' | 'info';
  message: string;
  block_id: string | null;
  line: number | null;
  target: string | null;
}

export interface Line {
  n: number;
  text: string;
  blocks: string[];
}

export interface Generated {
  target: Lang;
  code: string;
  lines: Line[];
  diagnostics: Diagnostic[];
  ok: boolean;
}

export interface TableResult {
  name: string;
  columns: string[];
  rows: any[][];
  total_rows: number;
}

export interface RunError {
  kind: string;
  message: string;
  detail: string;
  line: number | null;
  block_id: string | null;
}

export interface RunResult {
  target: Lang;
  ok: boolean;
  tables: TableResult[];
  stdout: string;
  plots: string[];
  error: RunError | null;
  code: string; // the code that ran
}

/** Where Python and R run, and where the browser loads them from (GET /api/runtime). */
export interface RuntimeConfig {
  run_in: 'browser' | 'server';
  pyodide: string;
  webr: string;
  webr_repo: string;
}

/** A program ready to run in the browser (POST /api/projects/<name>/job). */
export interface Job {
  target: 'python' | 'r';
  project: string;
  code: string;
  harness: string;
  names: string[];
  files: { path: string; url: string; version: string }[];
  timeout: number; // seconds
}

/** What running a Job produced, sent back to be turned into a RunResult. */
export interface Raw {
  stdout: string;
  timed_out: boolean;
  data?: Record<string, unknown> | null; // Python: the harness's result.json
  files?: Record<string, string>; // R: the harness's output files
  plots?: string[]; // R: every plot page as base64 PNG
}

export interface ParseResult {
  ok: boolean;
  lang: Lang;
  program: Program | null;
  spans: Record<string, number[]>;
  diagnostics: Diagnostic[];
}

export interface BlockSpec {
  type: string;
  family: string;
  labels: Record<Lang, string>;
  targets: string[];
  caption: string;
  single: boolean;
}

export interface Erd {
  tables: { name: string; rows: number; columns: { name: string; type: string; pk: boolean; fk: boolean }[] }[];
  links: { column: string; one: string; many: string; kind: string }[];
  unlinked: [string, string][];
}
