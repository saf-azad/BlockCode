// Round expression pills: compare, and/or, not, maths, is empty, in list, contains...
// Every pill can be edited in place; empty slots offer a menu, and condition pills from the
// palette can be dropped onto any slot.
import { useDroppable } from '@dnd-kit/core';
import { mk, parseLiteral } from '../ir';
import type { Block } from '../types';
import { ColumnPick, Pick, TextIn, useScope, useWords, type Scope } from './fields';

export const EXPR_KINDS: { kind: string; label: string; data: boolean; imperative: boolean }[] = [
  { kind: 'col', label: 'column', data: true, imperative: false },
  { kind: 'field', label: 'row field', data: false, imperative: true },
  { kind: 'var', label: 'variable', data: false, imperative: true },
  { kind: 'lit', label: 'value', data: true, imperative: true },
  { kind: 'cmp', label: '_ > _', data: true, imperative: true },
  { kind: 'and', label: 'and', data: true, imperative: true },
  { kind: 'or', label: 'or', data: true, imperative: true },
  { kind: 'not', label: 'not', data: true, imperative: true },
  { kind: 'math', label: '_ + _', data: true, imperative: true },
  { kind: 'isempty', label: 'is empty', data: true, imperative: true },
  { kind: 'inlist', label: 'in list', data: true, imperative: true },
  { kind: 'contains', label: 'contains', data: true, imperative: true },
  { kind: 'starts', label: 'starts with', data: true, imperative: true },
  { kind: 'ends', label: 'ends with', data: true, imperative: true },
];

/** A fresh expression of a palette kind, pre-filled with something sensible from the scope. */
export function makeExpr(kind: string, scope: Scope): Block {
  const first = (types?: string[]) => {
    const c = scope.columns.find((x) => !types || types.includes(x.type)) ?? scope.columns[0];
    return c?.name ?? '';
  };
  const subject = (types?: string[]): Block => {
    if (!scope.imperative) return mk('col', { name: first(types) });
    const rf = scope.rowFields[scope.rowFields.length - 1];
    if (rf) {
      const c = rf.columns.find((x) => !types || types.includes(x.type)) ?? rf.columns[0];
      return mk('field', { var: rf.name, name: c?.name ?? '' });
    }
    return mk('var', { name: scope.vars[0] ?? 'x' });
  };
  switch (kind) {
    case 'col': return mk('col', { name: first() });
    case 'lit': return mk('lit', { value: 0 });
    case 'var': return mk('var', { name: scope.vars[0] ?? 'x' });
    case 'field': {
      const rf = scope.rowFields[scope.rowFields.length - 1];
      return mk('field', { var: rf?.name ?? 'row', name: rf?.columns[0]?.name ?? '' });
    }
    case 'cmp': return mk('cmp', { op: '>' }, { a: subject(['int', 'float']), b: mk('lit', { value: 50 }) });
    case 'and': case 'or': return mk('logic', { op: kind });
    case 'not': return mk('not');
    case 'math': return mk('math', { op: '+' }, { a: subject(['int', 'float']), b: mk('lit', { value: 1 }) });
    case 'isempty': return mk('isempty', {}, { a: subject() });
    case 'inlist': return mk('inlist', { values: [] }, { a: subject(['text']) });
    case 'contains': case 'starts': case 'ends':
      return mk('text', { op: kind, value: '' }, { a: subject(['text']) });
    default: return mk('lit', { value: 0 });
  }
}

interface SlotProps {
  value: Block | undefined;
  onChange: (b: Block | null) => void;
  id: string; // unique per slot, for drag and drop
  hint?: string;
}

/** A place for one expression: shows the expression, or an empty dashed slot with a menu. */
export function Slot({ value, onChange, id, hint = 'condition' }: SlotProps) {
  const scope = useScope();
  const { setNodeRef, isOver } = useDroppable({ id: `slot:${id}`, data: { kind: 'slot', set: onChange, scope } });
  const kinds = EXPR_KINDS.filter((k) => (scope.imperative ? k.imperative : k.data));
  if (!value) {
    return (
      <label ref={setNodeRef} className={`slot${isOver ? ' over' : ''}`} title={`Drop a ${hint} here`}
        onPointerDown={(e) => e.stopPropagation()}>
        {hint}
        <select value="" onChange={(e) => e.target.value && onChange(makeExpr(e.target.value, scope))}
          aria-label={`Pick a ${hint}`}>
          <option value="">Pick…</option>
          {kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
        </select>
      </label>
    );
  }
  return (
    <span ref={setNodeRef} className={`slot-wrap${isOver ? ' over' : ''}`}>
      <Expr e={value} onChange={onChange} path={id} />
    </span>
  );
}

const CMP_SHOW: Record<string, Record<string, string>> = {
  sql: { '=': '=', '!=': '≠', '<': '<', '<=': '≤', '>': '>', '>=': '≥' },
  python: { '=': '==', '!=': '!=', '<': '<', '<=': '<=', '>': '>', '>=': '>=' },
  r: { '=': '==', '!=': '!=', '<': '<', '<=': '<=', '>': '>', '>=': '>=' },
};
const MATH_SHOW: Record<string, string> = { '+': '+', '-': '−', '*': '×', '/': '÷', '%': 'mod' };
const TEXT_SHOW: Record<string, string> = { contains: 'contains', starts: 'starts with', ends: 'ends with' };

function OpPick({ value, options, onChange, title }: {
  value: string; options: Record<string, string>; onChange: (v: string) => void; title: string;
}) {
  return (
    <label className="op" title={title} onPointerDown={(e) => e.stopPropagation()}>
      {options[value] ?? value}
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={title}>
        {Object.entries(options).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
    </label>
  );
}

function Lit({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const text = value === null || value === undefined ? '' : String(value);
  const isText = typeof value === 'string';
  return (
    <span className="f" title={isText ? 'Text value' : 'Number value'}>
      {isText && '"'}
      <input value={text} size={Math.max(1, text.length)} onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()} aria-label="Value"
        onChange={(e) => onChange(isText && !/^-?\d/.test(e.target.value) ? e.target.value : parseLiteral(e.target.value))} />
      {isText && '"'}
    </span>
  );
}

export function Expr({ e, onChange, path }: { e: Block; onChange: (b: Block | null) => void; path: string }) {
  const scope = useScope();
  const w = useWords();
  const set = (patch: Partial<Block>) => onChange({ ...e, ...patch });
  const field = (k: string, v: any) => set({ fields: { ...e.fields, [k]: v } });
  const child = (slot: string, hint = 'value') => (
    <Slot id={`${path}.${slot}`} hint={hint} value={e.inputs[slot]}
      onChange={(b) => {
        const inputs = { ...e.inputs };
        if (b) inputs[slot] = b; else delete inputs[slot];
        set({ inputs });
      }} />
  );
  const kx = <button className="kx" title="Remove" onPointerDown={(ev) => ev.stopPropagation()} onClick={() => onChange(null)}>×</button>;
  const data = !scope.imperative;

  switch (e.type) {
    case 'col':
      return <ColumnPick value={e.fields.name} onChange={(v) => field('name', v)} />;
    case 'lit':
      return <Lit value={e.fields.value} onChange={(v) => field('value', v)} />;
    case 'var':
      return <TextIn value={e.fields.name ?? ''} onChange={(v) => field('name', v.replace(/\W/g, ''))} title="Variable" placeholder="name" />;
    case 'field': {
      const rf = scope.rowFields.find((r) => r.name === e.fields.var) ?? scope.rowFields[scope.rowFields.length - 1];
      return (
        <span className="expr">
          <Pick value={e.fields.var} options={scope.rowFields.map((r) => r.name)} onChange={(v) => field('var', v)} title="Loop variable" />
          {scope.lang === 'r' ? '$' : '.'}
          <ColumnPick value={e.fields.name} columns={rf?.columns ?? []} onChange={(v) => field('name', v)} title="Field" />
          {kx}
        </span>
      );
    }
    case 'cmp':
      return (
        <span className="expr">
          {child('a')}
          <OpPick value={e.fields.op} options={CMP_SHOW[scope.lang]} onChange={(v) => field('op', v)} title="Comparison" />
          {child('b')}
          {kx}
        </span>
      );
    case 'logic': {
      const opts = scope.imperative && scope.lang === 'python' ? { and: 'and', or: 'or' } : { and: w.and, or: w.or };
      return (
        <span className="expr">
          {child('a', 'condition')}
          <OpPick value={e.fields.op} options={opts} onChange={(v) => field('op', v)} title="And / or" />
          {child('b', 'condition')}
          {kx}
        </span>
      );
    }
    case 'not':
      return (
        <span className="expr">
          <span>{scope.imperative && scope.lang === 'python' ? 'not' : w.not}</span>
          {child('a', 'condition')}
          {kx}
        </span>
      );
    case 'math':
      return (
        <span className="expr">
          {child('a')}
          <OpPick value={e.fields.op} options={MATH_SHOW} onChange={(v) => field('op', v)} title="Maths" />
          {child('b')}
          {kx}
        </span>
      );
    case 'isempty':
      return (
        <span className="expr">
          {child('a')}
          <span>{data ? (scope.lang === 'sql' ? 'is empty' : w.empty) : 'is empty'}</span>
          {kx}
        </span>
      );
    case 'inlist': {
      const values: any[] = e.fields.values ?? [];
      return (
        <span className="expr">
          {child('a')}
          <span>in</span>
          <TextIn value={values.map((v) => String(v)).join(', ')} placeholder="a, b"
            title="Values, separated by commas"
            onChange={(t) => field('values', t.split(',').map((x) => x.trim()).filter((x) => x !== '').map(parseLiteral))} />
          {kx}
        </span>
      );
    }
    case 'text':
      return (
        <span className="expr">
          {child('a')}
          <OpPick value={e.fields.op} options={TEXT_SHOW} onChange={(v) => field('op', v)} title="Text test" />
          <TextIn value={e.fields.value ?? ''} placeholder="text" onChange={(v) => field('value', v)} title="Text" />
          {kx}
        </span>
      );
    default:
      return <span className="expr">{e.type}{kx}</span>;
  }
}
