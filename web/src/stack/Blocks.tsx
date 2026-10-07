import { useDraggable, useDroppable } from '@dnd-kit/core';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Explainer } from '../explainers/Explainer';
import {
  C_BLOCKS, columnsAt, loopVars, removeBlock, resultColumns, setField, setInput, stackNames, variables,
} from '../ir';
import { useEdit, useStore, effectiveLang } from '../store';
import { blockColour } from '../theme';
import type { Block, Diagnostic, Lang, Program, TableInfo } from '../types';
import { Slot } from './Expr';
import { ColumnChips, ColumnPick, NumIn, Pick, ScopeProvider, TextIn, useScope, useWords, type Scope } from './fields';

// ---- shared wrappers -------------------------------------------------------------------------

function useDelayed(on: boolean, ms: number): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!on) {
      setShown(false);
      return;
    }
    const t = setTimeout(() => setShown(true), ms);
    return () => clearTimeout(t);
  }, [on, ms]);
  return shown;
}

export function useBlockProblems(id: string): Diagnostic[] {
  const { state } = useStore();
  const lang = effectiveLang(state);
  const diags = state.generated?.[lang]?.diagnostics ?? [];
  const run = state.run?.error?.block_id === id ? [{
    severity: 'error' as const, message: state.run.error.message, block_id: id, line: state.run.error.line, target: lang,
  }] : [];
  return [...diags.filter((d) => d.block_id === id && d.severity !== 'info' && d.severity !== 'sql'), ...run];
}

export function RemoveButton({ id }: { id: string }) {
  const { dispatch } = useStore();
  const edit = useEdit();
  return (
    <button className="x" title="Remove block" aria-label="Remove block"
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        edit((p) => removeBlock(p, id));
        dispatch({ type: 'hover', id: null });
      }}>×</button>
  );
}

function ProblemDot({ id }: { id: string }) {
  const probs = useBlockProblems(id);
  if (!probs.length) return null;
  const err = probs.some((p) => p.severity === 'error');
  return <span className={`problem-dot${err ? '' : ' warn'}`} title={probs.map((p) => p.message).join('\n')}>!</span>;
}

export function Gap({ parent, stack, index, accepts, className = 'gap' }: {
  parent: string | null; stack: string; index: number; accepts: 'step' | 'statement'; className?: string;
}) {
  const { setNodeRef, isOver, active } = useDroppable({
    id: `gap:${parent ?? 'top'}:${stack}:${index}`, data: { kind: 'gap', parent, stack, index, accepts },
  });
  const ok = active && active.data.current?.family === accepts;
  return <div ref={setNodeRef} className={`${className}${isOver && ok ? ' active' : ''}`} />;
}

interface ShellProps {
  b: Block;
  family: 'step' | 'statement';
  className: string;
  style?: React.CSSProperties;
  children: ReactNode;
  tipBelow?: boolean;
  removable?: boolean;
  label?: string;
}

/** Hover, focus, drag, remove and explainer behaviour shared by every block. */
function Shell({ b, family, className, style, children, tipBelow, removable = true, label }: ShellProps) {
  const { state, dispatch } = useStore();
  const edit = useEdit();
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `blk:${b.id}`, data: { kind: 'move', id: b.id, family, label: label ?? b.type },
  });
  const hovered = state.hover === b.id;
  const showTip = useDelayed(hovered && !isDragging, 450);
  const focus = state.focus === b.id;
  const [below, setBelow] = useState(!!tipBelow);
  const el = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!showTip || !el.current) return;
    // show the explainer above the block unless that would run off the top of the workspace
    const ws = el.current.closest('.workspace');
    const top = el.current.getBoundingClientRect().top - (ws?.getBoundingClientRect().top ?? 0);
    setBelow(!!tipBelow || top < 150);
  }, [showTip, tipBelow]);
  return (
    <div
      ref={(node) => {
        setNodeRef(node);
        el.current = node;
      }}
      id={`blk-${b.id}`}
      data-block={b.id}
      data-type={b.type}
      className={`${className}${focus ? ' focus' : ''}${hovered ? ' hovered' : ''}${isDragging ? ' dragging' : ''}`}
      style={showTip ? { ...style, zIndex: 60 } : style}
      onMouseOver={(e) => {
        e.stopPropagation();
        dispatch({ type: 'hover', id: b.id });
      }}
      onClick={(e) => {
        e.stopPropagation();
        dispatch({ type: 'focus', id: b.id });
      }}
      {...attributes}
      {...listeners}
      role="group"
      aria-label={label ?? b.type}
      tabIndex={-1}
    >
      {children}
      {removable && <ProblemDot id={b.id} />}
      {removable && (
        <button className="x" title="Remove block" aria-label="Remove block"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            edit((p) => removeBlock(p, b.id));
            dispatch({ type: 'hover', id: null });
          }}>×</button>
      )}
      {showTip && <Explainer type={b.type} block={b} placement={below ? 'below' : 'above'} />}
    </div>
  );
}

// ---- scope helpers -----------------------------------------------------------------------------

export function useStatementScope(id: string): Partial<Scope> {
  const { state } = useStore();
  const tables = state.project?.tables ?? [];
  const loops = loopVars(state.program, id);
  return {
    imperative: true,
    vars: variables(state.program),
    rowFields: loops.filter((l) => l.over).map((l) => ({ name: l.name, columns: resultColumns(state.program, l.over!, tables) })),
    stacks: stackNames(state.program),
  };
}

// ---- data stacks ------------------------------------------------------------------------------

export function DataStack({ b, parent, stack, index }: { b: Block; parent: string | null; stack: string; index: number }) {
  const { state } = useStore();
  const lang = effectiveLang(state);
  const tables = state.project?.tables ?? [];
  const steps = b.stacks.steps ?? [];
  const all = [b, ...steps];
  void parent; void stack; void index;
  return (
    <div className="stack" data-stack={b.fields.name}>
      {all.map((blk, i) => {
        const cols = columnsAt(b, i === 0 ? 0 : i - 1, tables);
        const first = i === 0;
        const last = i === all.length - 1;
        const colour = blockColour(lang, blk.type);
        return (
          <ScopeProvider key={blk.id} value={{ columns: cols, imperative: false }}>
            {!first && <Gap parent={b.id} stack="steps" index={i - 1} accepts="step" className="gap stack-gap" />}
            <Shell b={blk} family={first ? 'statement' : 'step'} label={labelFor(blk, lang, state.specs)}
              className={`blk${first ? ' first' : ''}${last ? ' last' : ''}`}
              style={{ background: colour?.bg ?? '#eee', zIndex: all.length - i }}
              tipBelow={first} removable>
              <StepBody b={blk} from={b} tables={tables} />
              {!last && <span className="stud" style={{ background: colour?.bg }} />}
            </Shell>
          </ScopeProvider>
        );
      })}
      <Gap parent={b.id} stack="steps" index={steps.length} accepts="step" className="gap stack-gap" />
    </div>
  );
}

function labelFor(b: Block, lang: Lang, specs: Record<string, { labels: Record<Lang, string> }>): string {
  if (b.type === 'join') {
    if (lang === 'sql') return b.fields.how === 'left' ? 'LEFT JOIN' : 'JOIN';
    if (lang === 'r') return b.fields.how === 'left' ? 'left_join' : 'inner_join';
    return 'merge';
  }
  if (b.type === 'from' && lang !== 'sql') return 'From';
  if (b.type === 'having' && lang === 'python') return 'filter groups';
  return specs[b.type]?.labels?.[lang] ?? b.type;
}

function StepBody({ b, from, tables }: { b: Block; from: Block; tables: TableInfo[] }) {
  const { state } = useStore();
  const edit = useEdit();
  const lang = effectiveLang(state);
  const w = useWords();
  const scope = useScope();
  const f = (k: string, v: any) => edit((p) => setField(p, b.id, k, v));
  const label = <span className="kw">{labelFor(b, lang, state.specs)}</span>;
  const cond = (slot: string, hint = 'condition') => (
    <Slot id={`${b.id}.${slot}`} hint={hint} value={b.inputs[slot]} onChange={(e) => edit((p) => setInput(p, b.id, slot, e))} />
  );

  switch (b.type) {
    case 'from': {
      const t = tables.find((x) => x.name === b.fields.table);
      const multi = stackNames(state.program).length > 1 || b.fields.name !== 'out';
      return (
        <>
          {label}
          <Pick className="f src" value={b.fields.table} options={tables.map((x) => x.name)} onChange={(v) => f('table', v)} title="Table" />
          {t && <span className="small-note">{t.rows.toLocaleString()} rows</span>}
          {multi && <><span className="word">→</span><TextIn value={b.fields.name ?? 'out'} onChange={(v) => f('name', v.replace(/\W/g, '') || 'out')} title="Name of the result" /></>}
        </>
      );
    }
    case 'join': {
      const t = tables.find((x) => x.name === b.fields.table);
      const shared = (t?.columns ?? []).filter((c) => scope.columns.some((x) => x.name === c.name)).map((c) => c.name);
      return (
        <>
          {label}
          <Pick value={b.fields.table} options={tables.filter((x) => x.name !== from.fields.table).map((x) => x.name)} onChange={(v) => f('table', v)} title="Table to join" />
          <span className="word">{w.using}</span>
          <Pick value={b.fields.on} options={shared} onChange={(v) => f('on', v)} title="Column in both tables" placeholder="column" />
          <Pick value={b.fields.how ?? 'inner'} options={[{ value: 'inner', label: 'matching rows' }, { value: 'left', label: 'keep all rows' }]} onChange={(v) => f('how', v)} title="Keep rows with no match?" />
        </>
      );
    }
    case 'where':
    case 'having':
      return <>{label}{cond('cond')}</>;
    case 'derive':
      return (
        <>
          {label}
          <TextIn value={b.fields.name ?? ''} onChange={(v) => f('name', v.replace(/\W/g, ''))} title="New column name" placeholder="name" />
          <span className="word">=</span>
          {cond('expr', 'value')}
        </>
      );
    case 'group': {
      const aggs: any[] = b.fields.aggs ?? [];
      const setAggs = (next: any[]) => f('aggs', next);
      const numeric = scope.columns.filter((c) => c.type === 'int' || c.type === 'float').map((c) => c.name);
      return (
        <>
          {label}
          <ColumnChips value={b.fields.by ?? []} onChange={(v) => f('by', v)} title="Group by column" />
          {aggs.map((a, i) => (
            <span key={i} className="chips">
              <span className="agg">
                <Pick value={a.func} options={['avg', 'count', 'sum', 'min', 'max'].map((x) => ({ value: x, label: w[x] }))}
                  onChange={(v) => setAggs(aggs.map((x, j) => (j === i ? { ...x, func: v, column: v === 'count' ? x.column : x.column ?? numeric[0] } : x)))} title="Summary" />
                {(a.func !== 'count' || a.column) && <>of
                  <Pick value={a.column ?? ''} options={(a.func === 'count' ? [{ value: '', label: 'rows' }] : []).concat(scope.columns.map((c) => ({ value: c.name, label: c.name })))}
                    onChange={(v) => setAggs(aggs.map((x, j) => (j === i ? { ...x, column: v || null } : x)))} title="Column" /></>}
              </span>
              <span className="word">{w.as}</span>
              <TextIn value={a.as ?? ''} onChange={(v) => setAggs(aggs.map((x, j) => (j === i ? { ...x, as: v.replace(/\W/g, '') } : x)))} title="Name" />
              <button className="chip-x" title="Remove summary" onPointerDown={(e) => e.stopPropagation()}
                onClick={() => setAggs(aggs.filter((_, j) => j !== i))}>×</button>
            </span>
          ))}
          <button className="add" title="Add a summary" onPointerDown={(e) => e.stopPropagation()}
            onClick={() => setAggs([...aggs, { func: 'count', column: null, as: aggs.some((a) => a.as === 'n') ? `n${aggs.length + 1}` : 'n' }])}>+ summary</button>
        </>
      );
    }
    case 'select':
      return <>{label}<ColumnChips value={b.fields.columns ?? []} onChange={(v) => f('columns', v)} title="Keep column" /></>;
    case 'order': {
      const keys: any[] = b.fields.keys ?? [];
      const setKeys = (next: any[]) => f('keys', next);
      return (
        <>
          {label}
          {keys.map((k, i) => (
            <span key={i} className="chips">
              <ColumnPick value={k.column} onChange={(v) => setKeys(keys.map((x, j) => (j === i ? { ...x, column: v } : x)))} />
              <Pick value={k.desc ? 'desc' : 'asc'} options={[{ value: 'desc', label: 'high → low' }, { value: 'asc', label: 'low → high' }]}
                onChange={(v) => setKeys(keys.map((x, j) => (j === i ? { ...x, desc: v === 'desc' } : x)))} title="Direction" />
              {keys.length > 1 && <button className="chip-x" title="Remove" onPointerDown={(e) => e.stopPropagation()} onClick={() => setKeys(keys.filter((_, j) => j !== i))}>×</button>}
            </span>
          ))}
          <button className="add" title="Then sort by" onPointerDown={(e) => e.stopPropagation()}
            onClick={() => setKeys([...keys, { column: scope.columns[0]?.name ?? '', desc: false }])}>+</button>
        </>
      );
    }
    case 'limit':
      return <>{label}<NumIn value={b.fields.n ?? 5} onChange={(v) => f('n', v)} title="Number of rows" />{w.rows && <span className="word">{w.rows}</span>}</>;
    default:
      return label;
  }
}

// ---- statements (Python / R only blocks, plots) ------------------------------------------------

export function StatementList({ blocks, parent, stack }: { blocks: Block[]; parent: string | null; stack: string }) {
  return (
    <>
      {blocks.map((b, i) => (
        <div key={b.id} style={{ display: 'flex', flexDirection: 'column' }}>
          <Gap parent={parent} stack={stack} index={i} accepts="statement" className="gap stack-gap" />
          <Statement b={b} parent={parent} stack={stack} index={i} />
        </div>
      ))}
      <Gap parent={parent} stack={stack} index={blocks.length} accepts="statement" className="gap stack-gap" />
    </>
  );
}

export function Statement({ b, parent, stack, index }: { b: Block; parent: string | null; stack: string; index: number }) {
  const scope = useStatementScope(b.id);
  if (b.type === 'from') {
    return <ScopeProvider value={{ imperative: false }}><DataStack b={b} parent={parent} stack={stack} index={index} /></ScopeProvider>;
  }
  return (
    <ScopeProvider value={scope}>
      {b.type === 'plot' ? <PlotBlock b={b} /> : C_BLOCKS.has(b.type) ? <CBlock b={b} /> : <PyBlock b={b} />}
    </ScopeProvider>
  );
}

function NoSql() {
  const { state } = useStore();
  if (state.lang !== 'sql') return null;
  return <span className="nosql-chip" title="Python and R only"><b>!</b>No SQL equivalent</span>;
}

function PyBlock({ b }: { b: Block }) {
  const edit = useEdit();
  const scope = useScope();
  const slot = (name: string, hint = 'value') => (
    <Slot id={`${b.id}.${name}`} hint={hint} value={b.inputs[name]} onChange={(e) => edit((p) => setInput(p, b.id, name, e))} />
  );
  const f = (k: string, v: any) => edit((p) => setField(p, b.id, k, v));
  let body: ReactNode;
  switch (b.type) {
    case 'setvar':
      body = <><span className="kw">Set</span><TextIn value={b.fields.name ?? ''} onChange={(v) => f('name', v.replace(/\W/g, ''))} title="Variable name" /><span className="word">to</span>{slot('value')}</>;
      break;
    case 'changevar':
      body = <><span className="kw">Change</span><Pick value={b.fields.name} options={scope.vars} onChange={(v) => f('name', v)} title="Variable" /><span className="word">by</span>{slot('by')}</>;
      break;
    case 'print': {
      const args = Object.keys(b.inputs).sort((x, y) => parseInt(x.slice(3), 10) - parseInt(y.slice(3), 10));
      body = (
        <>
          <span className="kw">Print</span>
          {args.map((k) => <span key={k}>{slot(k)}</span>)}
          <button className="add" title="Print another value" onPointerDown={(e) => e.stopPropagation()}
            onClick={() => edit((p) => setInput(p, b.id, `arg${args.length}`, { id: `${b.id}a${args.length}${Date.now()}`, type: 'lit', fields: { value: '' }, inputs: {}, stacks: {} }))}>+</button>
        </>
      );
      break;
    }
    case 'raw':
      body = (
        <>
          <span className="kw">Code</span>
          <span className="tag-chip">{b.fields.lang === 'r' ? 'R' : 'Python'} only · runs as written</span>
          <textarea className="raw-code" value={b.fields.code ?? ''} spellCheck={false}
            onPointerDown={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}
            onChange={(e) => f('code', e.target.value)} aria-label="Code" />
        </>
      );
      break;
    default:
      body = <span className="kw">{b.type}</span>;
  }
  return (
    <Shell b={b} family="statement" className="pyblk" label={b.type}>
      {body}
      {b.type !== 'raw' && <NoSql />}
    </Shell>
  );
}

function CBlock({ b }: { b: Block }) {
  const edit = useEdit();
  const scope = useScope();
  const f = (k: string, v: any) => edit((p) => setField(p, b.id, k, v));
  const slot = (name: string, hint = 'condition') => (
    <Slot id={`${b.id}.${name}`} hint={hint} value={b.inputs[name]} onChange={(e) => edit((p) => setInput(p, b.id, name, e))} />
  );
  let head: ReactNode;
  if (b.type === 'foreach') {
    head = <>For each<TextIn value={b.fields.var ?? 'row'} onChange={(v) => f('var', v.replace(/\W/g, '') || 'row')} title="Row variable" />
      <span className="word">in</span>
      <Pick value={b.inputs.over?.fields?.name ?? ''} options={scope.stacks} title="Rows to step through"
        onChange={(v) => edit((p) => setInput(p, b.id, 'over', { id: b.inputs.over?.id ?? `${b.id}o`, type: 'var', fields: { name: v }, inputs: {}, stacks: {} }))} /></>;
  } else if (b.type === 'repeat') {
    head = <>Repeat{slot('times', 'times')}<span className="word">times, counting</span><TextIn value={b.fields.var ?? 'i'} onChange={(v) => f('var', v.replace(/\W/g, '') || 'i')} title="Counter" /></>;
  } else if (b.type === 'if') {
    head = <>If{slot('cond')}</>;
  } else {
    head = <>While{slot('cond')}</>;
  }
  const inner = (name: string) => (
    <div className="cbody">
      <div className="arm" />
      <div className="inner">
        <StatementList blocks={b.stacks[name] ?? []} parent={b.id} stack={name} />
        {!(b.stacks[name] ?? []).length && <EmptyBody parent={b.id} stack={name} />}
      </div>
    </div>
  );
  return (
    <Shell b={b} family="statement" className="cblock" label={b.type} removable={false}>
      <div className="chead">{head}<NoSql /><ProblemDot id={b.id} /><RemoveButton id={b.id} /></div>
      {inner('body')}
      {b.type === 'if' && (b.stacks.else ? (
        <>
          <div className="cmid">else
            <button className="chip-x" title="Remove else" onPointerDown={(e) => e.stopPropagation()}
              onClick={() => edit((p) => removeElse(p, b.id))}>×</button>
          </div>
          {inner('else')}
        </>
      ) : (
        <div className="cmid"><button className="add" onPointerDown={(e) => e.stopPropagation()}
          onClick={() => edit((p) => addElse(p, b.id))}>+ else</button></div>
      ))}
      <div className="cfoot" />
    </Shell>
  );
}

function addElse(p: Program, id: string): Program {
  return mapStacks(p, id, (s) => ({ ...s, else: s.else ?? [] }));
}

function removeElse(p: Program, id: string): Program {
  return mapStacks(p, id, (s) => {
    const { else: _drop, ...rest } = s;
    void _drop;
    return rest;
  });
}

function mapStacks(p: Program, id: string, fn: (s: Record<string, Block[]>) => Record<string, Block[]>): Program {
  const visit = (b: Block): Block => ({
    ...b,
    stacks: Object.fromEntries(Object.entries(b.id === id ? fn(b.stacks) : b.stacks).map(([k, v]) => [k, v.map(visit)])),
    inputs: b.inputs,
  });
  return { blocks: p.blocks.map(visit) };
}

function EmptyBody({ parent, stack }: { parent: string; stack: string }) {
  const { setNodeRef, isOver, active } = useDroppable({
    id: `empty:${parent}:${stack}`, data: { kind: 'gap', parent, stack, index: 0, accepts: 'statement' },
  });
  const ok = active?.data.current?.family === 'statement';
  return (
    <div ref={setNodeRef} className={`drop-end${isOver && ok ? ' active' : ''}`} style={{ minWidth: 300, padding: '8px 12px', fontSize: 13 }}>
      Drag blocks in here
    </div>
  );
}

const CHARTS = [
  { value: 'bar', label: 'bar' }, { value: 'line', label: 'line' }, { value: 'scatter', label: 'scatter' }, { value: 'hist', label: 'histogram' },
];

function PlotBlock({ b }: { b: Block }) {
  const { state } = useStore();
  const edit = useEdit();
  const scope = useScope();
  const tables = state.project?.tables ?? [];
  const lang = effectiveLang(state);
  const cols = resultColumns(state.program, b.fields.data ?? 'out', tables);
  const f = (k: string, v: any) => edit((p) => setField(p, b.id, k, v));
  const detached = lang === 'sql';
  return (
    <Shell b={b} family="statement" className={`blk first last${detached ? ' detached' : ''}`} label="plot"
      style={{ background: lang === 'r' ? '#E3F4E6' : '#ECE6FB' }}>
      <span className="kw">{lang === 'r' ? 'ggplot' : 'Plot'}</span>
      <Pick value={b.fields.chart} options={CHARTS} onChange={(v) => f('chart', v)} title="Chart type" />
      {scope.stacks.length > 1 && <><span className="word">of</span><Pick value={b.fields.data} options={scope.stacks} onChange={(v) => f('data', v)} title="Rows to plot" /></>}
      <span className="word">x</span>
      <ColumnPick value={b.fields.x} columns={cols} onChange={(v) => f('x', v)} title="x axis" />
      {b.fields.chart === 'hist' ? (
        <><span className="word">bins</span><NumIn value={b.fields.bins ?? 5} onChange={(v) => f('bins', Math.max(1, v))} title="Bins" /></>
      ) : (
        <><span className="word">y</span><ColumnPick value={b.fields.y} columns={cols} onChange={(v) => f('y', v)} title="y axis" /></>
      )}
      {detached && <span className="tag-chip">Detached</span>}
    </Shell>
  );
}
