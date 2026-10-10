// Immutable helpers over the Program IR, plus the column tracking the dropdowns need.
import type { Block, Program, TableInfo } from './types';

export const STEP_ORDER = ['join', 'derive', 'where', 'group', 'having', 'select', 'order', 'limit'];
export const SINGLE = new Set(['group', 'having', 'select', 'order', 'limit']);
export const DATA_STEPS = new Set(STEP_ORDER);
export const C_BLOCKS = new Set(['foreach', 'repeat', 'if', 'while']);
export const PY_ONLY = new Set(['setvar', 'changevar', 'print', 'foreach', 'repeat', 'if', 'while', 'raw']);

let counter = 0;
export function newId(): string {
  counter += 1;
  return `u${Date.now().toString(36)}${counter.toString(36)}`;
}

export function mk(type: string, fields: Record<string, any> = {}, inputs: Record<string, Block> = {},
  stacks: Record<string, Block[]> = {}): Block {
  return { id: newId(), type, fields, inputs, stacks };
}

export function* walk(blocks: Block[]): Generator<Block> {
  for (const b of blocks) {
    yield b;
    for (const child of Object.values(b.inputs)) yield* walk([child]);
    for (const stack of Object.values(b.stacks)) yield* walk(stack);
  }
}

export function find(program: Program, id: string): Block | null {
  for (const b of walk(program.blocks)) if (b.id === id) return b;
  return null;
}

/** Path to a block: the container (parent id + stack name, or null for top level) and index. */
export interface Place {
  parent: string | null; // null = top level
  stack: string; // stack name ("steps", "body", "else") or "" at top level
  index: number;
}

export function placeOf(program: Program, id: string): Place | null {
  const search = (blocks: Block[], parent: string | null, stack: string): Place | null => {
    for (let i = 0; i < blocks.length; i++) {
      const b = blocks[i];
      if (b.id === id) return { parent, stack, index: i };
      for (const [name, s] of Object.entries(b.stacks)) {
        const got = search(s, b.id, name);
        if (got) return got;
      }
    }
    return null;
  };
  return search(program.blocks, null, '');
}

/** Rebuild the tree, replacing blocks for which ``fn`` returns something new. */
export function mapBlocks(program: Program, fn: (b: Block) => Block | null | undefined): Program {
  const visit = (b: Block): Block => {
    const replaced = fn(b);
    const cur = replaced ?? b;
    const inputs: Record<string, Block> = {};
    let changed = cur !== b;
    for (const [k, v] of Object.entries(cur.inputs)) {
      inputs[k] = visit(v);
      if (inputs[k] !== v) changed = true;
    }
    const stacks: Record<string, Block[]> = {};
    for (const [k, v] of Object.entries(cur.stacks)) {
      stacks[k] = v.map(visit);
      if (stacks[k].some((x, i) => x !== v[i])) changed = true;
    }
    return changed ? { ...cur, inputs, stacks } : cur;
  };
  return { blocks: program.blocks.map(visit) };
}

export function updateBlock(program: Program, id: string, fn: (b: Block) => Block): Program {
  return mapBlocks(program, (b) => (b.id === id ? fn(b) : null));
}

export function setField(program: Program, id: string, field: string, value: any): Program {
  return updateBlock(program, id, (b) => ({ ...b, fields: { ...b.fields, [field]: value } }));
}

export function setInput(program: Program, id: string, slot: string, value: Block | null): Program {
  return updateBlock(program, id, (b) => {
    const inputs = { ...b.inputs };
    if (value) inputs[slot] = value;
    else delete inputs[slot];
    return { ...b, inputs };
  });
}

/** Remove a block from wherever it sits (statement, step or expression). */
export function removeBlock(program: Program, id: string): Program {
  const strip = (blocks: Block[]): Block[] =>
    blocks.filter((b) => b.id !== id).map((b) => {
      const inputs: Record<string, Block> = {};
      for (const [k, v] of Object.entries(b.inputs)) if (v.id !== id) inputs[k] = strip([v])[0];
      const stacks: Record<string, Block[]> = {};
      for (const [k, v] of Object.entries(b.stacks)) stacks[k] = strip(v);
      return { ...b, inputs, stacks };
    });
  return { blocks: strip(program.blocks) };
}

/** Insert a block into a container. Steps of a From stack are kept in clause order. */
export function insertBlock(program: Program, block: Block, parent: string | null, stack: string,
  index: number): Program {
  const place = (list: Block[]): Block[] => {
    const out = [...list];
    out.splice(Math.max(0, Math.min(index, out.length)), 0, block);
    return stack === 'steps' ? clauseOrder(out) : out;
  };
  if (parent === null) return { blocks: place(program.blocks) };
  return updateBlock(program, parent, (b) => ({
    ...b, stacks: { ...b.stacks, [stack]: place(b.stacks[stack] ?? []) },
  }));
}

export function moveBlock(program: Program, id: string, parent: string | null, stack: string,
  index: number): Program {
  const block = find(program, id);
  if (!block) return program;
  const from = placeOf(program, id);
  let idx = index;
  if (from && from.parent === parent && from.stack === stack && from.index < index) idx -= 1;
  return insertBlock(removeBlock(program, id), block, parent, stack, idx);
}

export function clauseOrder(steps: Block[]): Block[] {
  const rank = (b: Block) => {
    const i = STEP_ORDER.indexOf(b.type);
    return i < 0 ? STEP_ORDER.length : i;
  };
  return steps.map((b, i) => [b, i] as const).sort((a, z) => rank(a[0]) - rank(z[0]) || a[1] - z[1])
    .map(([b]) => b);
}

export function hasPythonOnly(program: Program): boolean {
  for (const b of walk(program.blocks)) if (PY_ONLY.has(b.type)) return true;
  return false;
}

// ---- columns in scope --------------------------------------------------------------------

export interface Col {
  name: string;
  type: string;
  typical?: number | string | null; // a value from the data, for new blocks' defaults
}

/** Columns visible to the step at ``index`` of a From stack (``index`` = steps.length for after
 * the whole stack). Mirrors blockcode/plan.py. */
export function columnsAt(from: Block, index: number, tables: TableInfo[]): Col[] {
  const byName = new Map(tables.map((t) => [t.name, t]));
  let cols: Col[] = (byName.get(from.fields.table)?.columns ?? []).map((c) => ({ name: c.name, type: c.type, typical: c.typical }));
  const steps = from.stacks.steps ?? [];
  for (const b of steps.slice(0, index)) {
    if (b.type === 'join') {
      const t = byName.get(b.fields.table);
      for (const c of t?.columns ?? []) {
        if (c.name !== b.fields.on && !cols.some((x) => x.name === c.name)) cols.push({ name: c.name, type: c.type, typical: c.typical });
      }
    } else if (b.type === 'derive' && b.fields.name) {
      cols = cols.filter((c) => c.name !== b.fields.name).concat({ name: b.fields.name, type: 'float' });
    } else if (b.type === 'group') {
      const keys: Col[] = (b.fields.by ?? []).map((k: string) => cols.find((c) => c.name === k) ?? { name: k, type: 'text' });
      const aggs: Col[] = (b.fields.aggs ?? []).map((a: any) => ({
        name: a.as, type: a.func === 'count' ? 'int' : a.func === 'avg' ? 'float' : cols.find((c) => c.name === a.column)?.type ?? 'float',
      }));
      cols = [...keys, ...aggs];
    } else if (b.type === 'select') {
      cols = (b.fields.columns ?? []).map((c: string) => cols.find((x) => x.name === c) ?? { name: c, type: 'text' });
    }
  }
  return cols;
}

/** Columns of the result of the stack called ``name`` (for For each, Plot and row fields). */
export function resultColumns(program: Program, name: string, tables: TableInfo[]): Col[] {
  for (const b of walk(program.blocks)) {
    if (b.type === 'from' && (b.fields.name || 'out') === name) {
      return columnsAt(b, (b.stacks.steps ?? []).length, tables);
    }
  }
  return [];
}

export function stackNames(program: Program): string[] {
  const names: string[] = [];
  for (const b of walk(program.blocks)) if (b.type === 'from') {
    const n = b.fields.name || 'out';
    if (!names.includes(n)) names.push(n);
  }
  return names;
}

export function freshStackName(program: Program): string {
  const names = new Set(stackNames(program));
  if (!names.has('out')) return 'out';
  let i = 2;
  while (names.has(`out${i}`)) i++;
  return `out${i}`;
}

/** The From block that owns a step (or is the block itself). */
export function ownerStack(program: Program, id: string): Block | null {
  for (const b of walk(program.blocks)) {
    if (b.type !== 'from') continue;
    if (b.id === id) return b;
    for (const x of walk(b.stacks.steps ?? [])) if (x.id === id) return b;
  }
  return null;
}

/** Index of the step that contains ``id`` (an expression inside it counts). */
export function stepIndex(from: Block, id: string): number {
  const steps = from.stacks.steps ?? [];
  for (let i = 0; i < steps.length; i++) {
    for (const x of walk([steps[i]])) if (x.id === id) return i;
  }
  return steps.length;
}

/** The loop variables in scope for a block inside For each / Repeat bodies. */
export function loopVars(program: Program, id: string): { name: string; over: string | null }[] {
  const out: { name: string; over: string | null }[] = [];
  const search = (blocks: Block[], scope: { name: string; over: string | null }[]): boolean => {
    for (const b of blocks) {
      if (b.id === id) {
        out.push(...scope);
        return true;
      }
      let inner = scope;
      if (b.type === 'foreach') inner = [...scope, { name: b.fields.var || 'row', over: b.inputs.over?.fields?.name ?? null }];
      if (b.type === 'repeat') inner = [...scope, { name: b.fields.var || 'i', over: null }];
      for (const v of Object.values(b.inputs)) if (search([v], inner)) return true;
      for (const s of Object.values(b.stacks)) if (search(s, inner)) return true;
    }
    return false;
  };
  search(program.blocks, []);
  return out;
}

export function variables(program: Program): string[] {
  const names: string[] = [];
  for (const b of walk(program.blocks)) {
    if (b.type === 'setvar' && b.fields.name && !names.includes(b.fields.name)) names.push(b.fields.name);
  }
  return names;
}

/** Turn what a learner typed into a literal: numbers stay numbers, the rest is text. */
export function parseLiteral(text: string): string | number | boolean | null {
  const t = text.trim();
  if (/^-?\d+$/.test(t)) return parseInt(t, 10);
  if (/^-?(\d+\.\d*|\.\d+)(e-?\d+)?$/i.test(t)) return parseFloat(t);
  if (t === 'true' || t === 'TRUE' || t === 'True') return true;
  if (t === 'false' || t === 'FALSE' || t === 'False') return false;
  const q = t.match(/^(['"])(.*)\1$/);
  return q ? q[2] : text;
}

export function showLiteral(v: any): string {
  if (v === null || v === undefined) return 'empty';
  if (typeof v === 'string') return /^-?\d+(\.\d+)?$/.test(v) ? `"${v}"` : v;
  return String(v);
}
