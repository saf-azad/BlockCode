// New blocks from the palette, pre-filled from what is on the workspace (columns, stacks, loops).
import { columnsAt, freshStackName, mk, ownerStack, stackNames, resultColumns, variables, walk } from '../ir';
import type { Col } from '../ir';
import type { Block, Program, TableInfo } from '../types';

const numeric = (t: string) => t === 'int' || t === 'float';

export function makeBlock(type: string, program: Program, tables: TableInfo[], opts: {
  from?: Block | null; table?: string; loopVar?: { name: string; over: string | null } | null;
} = {}): Block {
  const from = opts.from ?? null;
  // columns where the new block will sit: steps before Group by see the table's columns,
  // steps after it see the groups
  const steps = from?.stacks.steps ?? [];
  const groupAt = steps.findIndex((s) => s.type === 'group');
  const beforeGroup = ['join', 'derive', 'where', 'group'].includes(type);
  const at = beforeGroup && groupAt >= 0 ? groupAt : steps.length;
  const cols = from ? columnsAt(from, at, tables) : [];
  const firstNum = cols.find((c) => numeric(c.type))?.name ?? cols[0]?.name ?? '';
  const firstText = cols.find((c) => c.type === 'text')?.name ?? cols[0]?.name ?? '';
  const stacks = stackNames(program);
  const lastStack = stacks[stacks.length - 1] ?? 'out';

  switch (type) {
    case 'from':
      return mk('from', { table: opts.table ?? tables[0]?.name ?? '', name: freshStackName(program) }, {}, { steps: [] });
    case 'join': {
      const used = new Set([from?.fields.table, ...(from?.stacks.steps ?? []).filter((s) => s.type === 'join').map((s) => s.fields.table)]);
      const candidate = tables.find((t) => !used.has(t.name) && t.columns.some((c) => cols.some((x) => x.name === c.name)))
        ?? tables.find((t) => !used.has(t.name));
      const on = candidate?.columns.find((c) => cols.some((x) => x.name === c.name))?.name ?? '';
      return mk('join', { table: candidate?.name ?? '', on, how: 'inner' });
    }
    case 'where':
      return mk('where', {}, { cond: mk('cmp', { op: '>' }, { a: mk('col', { name: firstNum }), b: mk('lit', { value: 50 }) }) });
    case 'derive':
      return mk('derive', { name: 'new_column' }, { expr: mk('math', { op: '*' }, { a: mk('col', { name: firstNum }), b: mk('lit', { value: 2 }) }) });
    case 'group': {
      const aggs = [{ func: 'count', column: null, as: 'n' }];
      if (firstNum && firstNum !== firstText) aggs.unshift({ func: 'avg', column: firstNum as any, as: `avg_${firstNum}` });
      return mk('group', { by: firstText ? [firstText] : [], aggs });
    }
    case 'having': {
      const g = from?.stacks.steps?.find((s) => s.type === 'group');
      const alias = g?.fields.aggs?.find((a: any) => a.func === 'count')?.as ?? g?.fields.aggs?.[0]?.as ?? 'n';
      return mk('having', {}, { cond: mk('cmp', { op: '>=' }, { a: mk('col', { name: alias }), b: mk('lit', { value: 10 }) }) });
    }
    case 'select':
      return mk('select', { columns: cols.slice(0, 2).map((c) => c.name) });
    case 'order': {
      const g = from?.stacks.steps?.find((s) => s.type === 'group');
      const key = g?.fields.aggs?.[0]?.as ?? firstNum;
      return mk('order', { keys: [{ column: key, desc: true }] });
    }
    case 'limit':
      return mk('limit', { n: 5 });
    case 'setvar':
      return mk('setvar', { name: freshVar(program) }, { value: mk('lit', { value: 0 }) });
    case 'changevar':
      return mk('changevar', { name: variables(program)[0] ?? 'total' }, { by: mk('lit', { value: 1 }) });
    case 'print': {
      const lv = opts.loopVar;
      if (lv && lv.over) {
        const rc = resultColumns(program, lv.over, tables);
        return mk('print', {}, { arg0: mk('field', { var: lv.name, name: rc[0]?.name ?? '' }) });
      }
      if (lv) return mk('print', {}, { arg0: mk('var', { name: lv.name }) });
      return mk('print', {}, { arg0: mk('lit', { value: 'Hello' }) });
    }
    case 'foreach':
      return mk('foreach', { var: 'row' }, { over: mk('var', { name: lastStack }) }, { body: [] });
    case 'repeat':
      return mk('repeat', { var: 'i' }, { times: mk('lit', { value: 3 }) }, { body: [] });
    case 'if':
      return mk('if', {}, {}, { body: [] });
    case 'while':
      return mk('while', {}, {}, { body: [] });
    case 'plot': {
      const rc = resultColumns(program, lastStack, tables);
      return mk('plot', { data: lastStack, bins: 5, ...plotFields({ chart: defaultChart(program, lastStack, rc) }, rc) });
    }
    case 'raw':
      return mk('raw', { lang: 'python', code: '# your code here' });
    default:
      return mk(type);
  }
}

function freshVar(program: Program): string {
  const used = new Set(variables(program));
  for (const n of ['total', 'count', 'best', 'x', 'y']) if (!used.has(n)) return n;
  let i = 2;
  while (used.has(`x${i}`)) i++;
  return `x${i}`;
}

/** The From stack a new step should go into: the one holding the focused block, else the last. */
export function targetStack(program: Program, focus: string | null): Block | null {
  if (focus) {
    const own = ownerStack(program, focus);
    if (own) return own;
  }
  let last: Block | null = null;
  for (const b of walk(program.blocks)) if (b.type === 'from') last = b;
  return last;
}

/** A chart that suits the rows: bars for a few labelled rows (after Group by or Limit), else a
 * scatter of two number columns, else a histogram. A bar for every row of a big table can't
 * be read and takes ages to draw. */
function defaultChart(program: Program, stack: string, cols: Col[]): string {
  let from: Block | null = null;
  for (const b of walk(program.blocks)) if (b.type === 'from' && (b.fields.name || 'out') === stack) from = b;
  const steps = from?.stacks.steps ?? [];
  const few = steps.some((s) => (s.type === 'group' && (s.fields.by ?? []).length) || (s.type === 'limit' && s.fields.n <= 100));
  const nums = cols.filter((c) => numeric(c.type)).length;
  if (few || !nums) return 'bar';
  return nums >= 2 ? 'scatter' : 'hist';
}

/** Plot settings with every axis on a column that exists and suits the chart: number columns
 * where the chart needs numbers. Keeps the current choice whenever it still works. */
export function plotFields(fields: Record<string, any>, cols: Col[]): { chart: string; x: string; y: string } {
  const chart = fields.chart ?? 'bar';
  const nums = cols.filter((c) => numeric(c.type)).map((c) => c.name);
  const all = cols.map((c) => c.name);
  const text = cols.filter((c) => !numeric(c.type)).map((c) => c.name);
  const pick = (cur: string | undefined, ok: string[], ...prefer: (string | undefined)[]) =>
    (cur && ok.includes(cur) ? cur : prefer.find((p) => p && ok.includes(p))) ?? ok[0] ?? cur ?? '';
  if (!cols.length) return { chart, x: fields.x ?? '', y: fields.y ?? '' };
  if (chart === 'hist') return { chart, x: pick(fields.x, nums.length ? nums : all, fields.y), y: fields.y ?? '' };
  if (chart === 'scatter') {
    const ok = nums.length ? nums : all;
    const x = pick(fields.x, ok, ...ok.filter((c) => c !== fields.y));
    return { chart, x, y: pick(fields.y, ok, ...ok.filter((c) => c !== x)) };
  }
  const x = pick(fields.x, all, text[0]);
  return { chart, x, y: pick(fields.y, nums.length ? nums : all, ...nums.filter((c) => c !== x)) };
}
