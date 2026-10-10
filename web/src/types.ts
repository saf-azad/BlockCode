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
  unique?: boolean;
  typical?: number | string | null; // median number or most common text
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
