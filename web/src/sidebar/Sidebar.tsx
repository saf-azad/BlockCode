import { useDraggable } from '@dnd-kit/core';
import { useRef, useState } from 'react';
import {
  C_BLOCKS, columnsAt, find, insertBlock, loopVars, ownerStack, placeOf, resultColumns, setInput, SINGLE, stepIndex, variables, walk,
} from '../ir';
import { deleteTable } from '../local';
import { Confirm } from '../Modal';
import { effectiveLang, useStore } from '../store';
import { blockColour } from '../theme';
import type { Block, Program, TableInfo } from '../types';
import { EXPR_KINDS, makeExpr } from '../stack/Expr';
import type { DragData } from '../stack/dnd';
import { WORDS } from '../stack/fields';
import { makeBlock, targetStack } from '../stack/make';
import { PasteData } from './PasteData';
import { useUpload } from './upload';

const DATA_PALETTE = ['join', 'derive', 'where', 'group', 'having', 'select', 'order', 'limit'];
const PY_PALETTE = ['foreach', 'print', 'setvar', 'changevar', 'if', 'repeat', 'while', 'plot'];
const PY_LABEL: Record<string, string> = {
  foreach: 'For each', print: 'Print', setvar: 'Set var', changevar: 'Change var', if: 'If / else', repeat: 'Repeat',
  while: 'While', plot: 'Plot',
};

function Draggable({ data, children, className, style, onClick, disabled, title }: {
  data: DragData; children: React.ReactNode; className: string; style?: React.CSSProperties; onClick?: () => void;
  disabled?: boolean; title?: string;
}) {
  const id = `pal:${data.kind}:${data.type ?? data.table}`;
  const { attributes, listeners, setNodeRef } = useDraggable({ id, data, disabled });
  return (
    <button ref={setNodeRef} className={className} style={style} onClick={onClick} disabled={disabled} title={title}
      {...attributes} {...listeners} type="button">
      {children}
    </button>
  );
}

/** Add a block where it makes sense: steps into the focused (or last) stack; statements after
 * the focused statement, or inside a focused For each / If. */
function addFromPalette(type: string, program: Program, focus: string | null, tables: TableInfo[]):
  { program: Program; id: string } | { error: string } {
  if (type === 'from' || DATA_PALETTE.includes(type)) {
    let p = program;
    let from = type === 'from' ? null : targetStack(p, focus);
    if (!from) {
      if (!tables.length) return { error: 'Drop a CSV first, so there is a table to start from.' };
      const src = makeBlock('from', p, tables);
      p = insertBlock(p, src, null, '', 0);
      if (type === 'from') return { program: p, id: src.id };
      from = src;
    }
    if (SINGLE.has(type) && (from.stacks.steps ?? []).some((s) => s.type === type)) {
      return { error: `This stack already has a ${type} block.` };
    }
    const b = makeBlock(type, p, tables, { from });
    return { program: insertBlock(p, b, from.id, 'steps', (from.stacks.steps ?? []).length), id: b.id };
  }
  // statements
  let parent: string | null = null;
  let stack = '';
  let index = program.blocks.length;
  const focused = focus ? find(program, focus) : null;
  if (focused && C_BLOCKS.has(focused.type)) {
    parent = focused.id;
    stack = 'body';
    index = (focused.stacks.body ?? []).length;
  } else if (focused) {
    const place = placeOf(program, focused.id);
    if (place && place.stack !== 'steps') {
      parent = place.parent;
      stack = place.stack;
      index = place.index + 1;
    }
  }
  const lv = parent ? loopVars(program, parent) : [];
  const parentBlock = parent ? find(program, parent) : null;
  const loop = parentBlock?.type === 'foreach'
    ? { name: parentBlock.fields.var || 'row', over: parentBlock.inputs.over?.fields?.name ?? null }
    : lv[lv.length - 1] ?? null;
  const b = makeBlock(type, program, tables, { loopVar: loop });
  return { program: insertBlock(program, b, parent, stack, index), id: b.id };
}

/** Clicking a condition pill fills the first empty slot of the focused block. */
function fillSlot(program: Program, focus: string | null, kind: string, tables: TableInfo[]): Program | null {
  if (!focus) return null;
  const b = find(program, focus);
  if (!b) return null;
  const slot = ({ where: 'cond', having: 'cond', if: 'cond', while: 'cond', derive: 'expr', setvar: 'value' } as Record<string, string>)[b.type];
  if (!slot || b.inputs[slot]) return null;
  const from = ownerStack(program, focus);
  const columns = from ? columnsAt(from, stepIndex(from, focus), tables) : [];
  const loops = loopVars(program, focus);
  const scope = {
    lang: 'sql' as const, columns, imperative: !from, vars: variables(program),
    rowFields: loops.filter((l) => l.over).map((l) => ({ name: l.name, columns: resultColumns(program, l.over!, tables) })),
    stacks: [], tables: [],
  };
  return setInput(program, b.id, slot, makeExpr(kind, scope));
}

export function Sidebar() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);
  const tables = state.project?.tables ?? [];
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useUpload();
  const target = targetStack(state.program, state.focus);
  const w = WORDS[lang];
  const [pasting, setPasting] = useState(false);

  const add = (type: string) => {
    const got = addFromPalette(type, state.program, state.focus, tables);
    if ('error' in got) {
      dispatch({ type: 'toast', message: got.error });
      return;
    }
    dispatch({ type: 'program', program: got.program });
    dispatch({ type: 'focus', id: got.id });
  };

  const label = (type: string) => {
    if (type === 'join') return w.join;
    if (type === 'having' && lang === 'python') return 'filter groups';
    return state.specs[type]?.labels?.[lang] ?? type;
  };

  return (
    <aside className="sidebar" aria-label="Tables and blocks">
      <div className="section">
        <div className="section-head">
          <div className="section-title">Tables</div>
          <button className={`btn tiny${state.erdOpen ? ' on' : ''}`} title="Sketch how these tables link up" disabled={!tables.length}
            onClick={() => dispatch({ type: 'erd', open: !state.erdOpen })}>
            <svg width="14" height="12" viewBox="0 0 14 12" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="0.8" y="0.8" width="4.4" height="4.4" /><rect x="8.8" y="0.8" width="4.4" height="4.4" /><rect x="4.8" y="6.8" width="4.4" height="4.4" /><path d="M3 5.2 L7 6.8 M11 5.2 L7 6.8" /></svg>
            ERD
          </button>
        </div>
        {tables.map((t) => <TableCard key={t.name} t={t} />)}
        {state.uploading > 0 && <div className="reading" role="status">Reading your file…</div>}
        {tables.length ? (
          <button className="drop-target" onClick={() => fileRef.current?.click()}>+ Add another CSV</button>
        ) : (
          <button className="drop-target big" onClick={() => fileRef.current?.click()} data-testid="add-csv">
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true"><path d="M13 17V4M7.5 9.5 13 4l5.5 5.5M4 18v4h18v-4" strokeLinecap="round" strokeLinejoin="round" /></svg>
            <b>Add a CSV file</b>
            <span>Click to choose, or drop it here</span>
          </button>
        )}
        <button className="linkish" onClick={() => setPasting(true)}>or paste data from a spreadsheet</button>
        <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values" multiple className="sr-only" aria-label="Choose CSV files"
          onChange={(e) => {
            if (e.target.files?.length) upload(e.target.files);
            e.target.value = '';
          }} />
        {pasting && <PasteData onClose={() => setPasting(false)} />}
      </div>

      <div className="section">
        <div className="section-title">Blocks</div>
        {!tables.length && <div className="locked-note">Add a table and these blocks come alive.</div>}
        <div className="palette">
          <Draggable className="pal-block" data={{ kind: 'new', type: 'from', family: 'statement', label: lang === 'sql' ? 'FROM' : 'From' }}
            style={{ background: blockColour(lang, 'from')?.bg }} onClick={() => add('from')} title="Start a new stack from a table" disabled={!tables.length}>
            {lang === 'sql' ? 'FROM' : 'From'}
          </Draggable>
          {DATA_PALETTE.map((type) => {
            const taken = !!target && SINGLE.has(type) && (target.stacks.steps ?? []).some((s: Block) => s.type === type);
            return (
              <Draggable key={type} className="pal-block" disabled={taken || !tables.length}
                data={{ kind: 'new', type, family: 'step', label: label(type) }}
                style={{ background: blockColour(lang, type)?.bg }}
                title={taken ? 'Already in the stack' : state.specs[type]?.caption ?? 'Add to the stack'}
                onClick={() => add(type)}>
                {label(type)}
              </Draggable>
            );
          })}
        </div>
      </div>

      <div className="section">
        <div className="section-title">Conditions</div>
        <div className="pills">
          {EXPR_KINDS.filter((k) => !['col', 'lit', 'var', 'field', 'starts', 'ends'].includes(k.kind)).map((k) => (
            <Draggable key={k.kind} className="pal-pill" data={{ kind: 'expr', type: k.kind, family: 'expr', label: k.label }}
              title="Drag onto a slot in a block (or click to fill the selected block)"
              onClick={() => {
                const next = fillSlot(state.program, state.focus, k.kind, tables);
                if (next) dispatch({ type: 'program', program: next });
                else dispatch({ type: 'toast', message: 'Drag this onto an empty slot in a block.' });
              }}>
              {k.label}
            </Draggable>
          ))}
        </div>
      </div>

      <div className="section">
        <div className="section-title">Python &amp; R</div>
        <div className="palette">
          {PY_PALETTE.map((type) => (
            <Draggable key={type} className="pal-block dashed" data={{ kind: 'new', type, family: 'statement', label: PY_LABEL[type] }}
              style={{ background: '#FFFFFF' }} title={state.specs[type]?.caption ?? ''} onClick={() => add(type)}>
              {type === 'plot' && lang === 'r' ? 'ggplot' : PY_LABEL[type]}
            </Draggable>
          ))}
        </div>
      </div>
    </aside>
  );
}

const SHOWN = 8;

function TableCard({ t }: { t: TableInfo }) {
  const { state, dispatch } = useStore();
  const [all, setAll] = useState(false);
  const [removing, setRemoving] = useState(false);
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: `table:${t.name}`, data: { kind: 'table', table: t.name, family: 'statement', label: `FROM ${t.name}` } satisfies DragData,
  });
  const users = [...walk(state.program.blocks)].filter((b) => (b.type === 'from' || b.type === 'join') && b.fields.table === t.name).length;
  const cols = all ? t.columns : t.columns.slice(0, SHOWN);
  const stop = (e: React.PointerEvent | React.KeyboardEvent) => e.stopPropagation();
  return (
    <>
      <div ref={setNodeRef} className="table-card" {...attributes} {...listeners} title={`Drag onto the workspace to start a stack from ${t.name}`}>
        <div className="head">
          <b>{t.name}</b>
          <span>{t.rows.toLocaleString()} row{t.rows === 1 ? '' : 's'}</span>
          <button className="tx" title={`Remove ${t.name}`} aria-label={`Remove table ${t.name}`} onPointerDown={stop} onKeyDown={stop}
            onClick={() => setRemoving(true)}>×</button>
        </div>
        <div className="cols">
          {cols.map((c) => (
            <div key={c.name}>
              <div className="col"><span title={c.name}>{c.name}</span><i>{c.type}</i></div>
              {c.empty > 0 && <div className="empty">{c.empty.toLocaleString()} empty value{c.empty === 1 ? '' : 's'}</div>}
            </div>
          ))}
          {t.columns.length > SHOWN && (
            <button className="more" onPointerDown={stop} onKeyDown={stop} onClick={() => setAll(!all)}>
              {all ? 'Show fewer columns' : `+ ${t.columns.length - SHOWN} more column${t.columns.length - SHOWN === 1 ? '' : 's'}`}
            </button>
          )}
        </div>
      </div>
      {removing && (
        <Confirm title={`Remove ${t.name}?`} action="Remove table" onClose={() => setRemoving(false)}
          onConfirm={() => { deleteTable(t.name); dispatch({ type: 'removeTable', name: t.name }); }}>
          <p>{users ? `${users} block${users > 1 ? 's use' : ' uses'} this table and will need another one. ` : ''}The table is removed from this browser; your original file is not touched.</p>
        </Confirm>
      )}
    </>
  );
}
