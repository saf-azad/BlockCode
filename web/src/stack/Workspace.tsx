import { useDroppable } from '@dnd-kit/core';
import { useEffect, useRef, useState } from 'react';
import { insertBlock, stackNames } from '../ir';
import { PasteData } from '../sidebar/PasteData';
import { useUpload } from '../sidebar/upload';
import { effectiveLang, useStore } from '../store';
import { blockColour } from '../theme';
import type { Lang } from '../types';
import { ScopeProvider } from './fields';
import { StatementList } from './Blocks';
import { makeBlock } from './make';

function EndZone({ index }: { index: number }) {
  const { setNodeRef, isOver, active } = useDroppable({
    id: 'gap:top:end', data: { kind: 'gap', parent: null, stack: '', index, accepts: 'statement' },
  });
  const ok = active?.data.current?.family === 'statement';
  if (!active || !ok) return <div ref={setNodeRef} style={{ height: 40 }} />;
  return <div ref={setNodeRef} className={`drop-end${isOver ? ' active' : ''}`}>+ Drop here to add it to the program</div>;
}

export function Workspace() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);
  const upload = useUpload();
  const tables = (state.project?.tables ?? []).map((t) => t.name);

  // Dragging a file anywhere over the window shows the drop overlay.
  useEffect(() => {
    let depth = 0;
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth += 1;
      dispatch({ type: 'dropping', on: true });
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) dispatch({ type: 'dropping', on: false });
    };
    const over = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      const files = e.dataTransfer?.files;
      if (files?.length) upload(files);
      else dispatch({ type: 'dropping', on: false });
    };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', over);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('dragover', over);
      window.removeEventListener('drop', drop);
    };
  }, [dispatch, upload]);

  const blocks = state.program.blocks;
  return (
    <div className="center">
      <div className="workspace" onMouseLeave={() => dispatch({ type: 'hover', id: null })}
        onClick={() => dispatch({ type: 'focus', id: null })} data-testid="workspace">
        <ScopeProvider value={{ lang, tables, stacks: stackNames(state.program) }}>
          <div className="program">
            {!blocks.length && (tables.length ? <StartHint /> : <Welcome />)}
            <StatementList blocks={blocks} parent={null} stack="" />
            <EndZone index={blocks.length} />
          </div>
        </ScopeProvider>
        {(state.dropping || state.dropped) && <DropOverlay />}
      </div>
      <TriBar />
    </div>
  );
}

/** First visit: nothing loaded yet. */
function Welcome() {
  const upload = useUpload();
  const fileRef = useRef<HTMLInputElement>(null);
  const [pasting, setPasting] = useState(false);
  return (
    <div className="welcome" onClick={(e) => e.stopPropagation()} data-testid="welcome">
      <h1>Build data code with blocks</h1>
      <p className="lede">
        Add a CSV, snap blocks together, and read the same steps as <b>SQL</b>, <b>Python</b> (pandas) and <b>R</b> (dplyr).
        Type code instead, and the blocks build themselves.
      </p>
      <div className="welcome-actions">
        <button className="btn primary" onClick={() => fileRef.current?.click()}>Choose a CSV file</button>
        <button className="btn small" onClick={() => setPasting(true)}>Paste data</button>
        <span>or drop a file anywhere on this page</span>
      </div>
      <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,text/csv" multiple className="sr-only" aria-label="Choose a CSV file to start"
        onChange={(e) => { if (e.target.files?.length) upload(e.target.files); e.target.value = ''; }} />
      <ol className="steps">
        <li><b>1</b><span><em>Add your data.</em> Any CSV works: exports from Excel, Google Sheets or a database.</span></li>
        <li><b>2</b><span><em>Snap blocks.</em> Filter, group, join and sort. Hover any block to see what it does to the rows.</span></li>
        <li><b>3</b><span><em>Run and export.</em> See the result, then download code that runs on its own.</span></li>
      </ol>
      <p className="privacy">Your files stay in this browser. They're sent to the server only to run or export your code, and aren't kept there.</p>
      {pasting && <PasteData onClose={() => setPasting(false)} />}
    </div>
  );
}

/** Tables loaded, no blocks yet: one click starts a stack. */
function StartHint() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);
  const tables = state.project?.tables ?? [];
  const start = (table: string) => {
    const b = makeBlock('from', state.program, tables, { table });
    dispatch({ type: 'program', program: insertBlock(state.program, b, null, '', state.program.blocks.length) });
    dispatch({ type: 'focus', id: b.id });
  };
  return (
    <div className="start-hint" onClick={(e) => e.stopPropagation()}>
      <p>Start a stack from a table:</p>
      <div className="start-chips">
        {tables.map((t) => (
          <button key={t.name} className="pal-block start" style={{ background: blockColour(lang, 'from')?.bg }} onClick={() => start(t.name)}>
            {lang === 'sql' ? 'FROM' : 'From'} <span>{t.name}</span>
          </button>
        ))}
      </div>
      <p className="muted">
        Or drag a table here. Then add steps like <b>WHERE</b> and <b>GROUP BY</b> from the left, or type code in the Code tab and
        the blocks build themselves.
      </p>
    </div>
  );
}

function DropOverlay() {
  const { state, dispatch } = useStore();
  const t = state.dropped?.table;
  const notes = state.dropped?.notes ?? [];
  return (
    <div className="overlay" aria-live="polite" onClick={(e) => { e.stopPropagation(); dispatch({ type: 'dropped', dropped: null }); }}>
      <h2>{t ? `Loaded ${t.name}` : 'Drop to load your CSV'}</h2>
      {t && (
        <>
          <div className="found">
            <div className="top"><span style={{ fontFamily: 'var(--head)', fontWeight: 800, fontSize: 16, color: 'var(--ink)' }}>Columns we found</span><span>{t.rows.toLocaleString()} row{t.rows === 1 ? '' : 's'}</span></div>
            <div className="found-rows">
              {t.columns.map((c) => (
                <div className="row" key={c.name}><span>{c.name}</span><span>{c.type}{c.empty ? ` · ${c.empty.toLocaleString()} empty` : ''}</span></div>
              ))}
            </div>
            {notes.length > 0 && (
              <ul className="notes">{notes.map((n) => <li key={n}>{n}</li>)}</ul>
            )}
          </div>
          <div style={{ fontSize: 15, color: 'var(--muted)' }}>
            Loaded as the table <span style={{ fontFamily: 'var(--mono)' }}>{t.name}</span>. Pick it in any FROM or JOIN block.
          </div>
        </>
      )}
      {!t && <div style={{ fontSize: 15, color: 'var(--muted)' }}>It becomes a table you can pick in any FROM or JOIN block.</div>}
    </div>
  );
}

const TRI: { lang: Lang; label: string; bg: string; fg?: string }[] = [
  { lang: 'sql', label: 'SQL', bg: '#111111', fg: 'var(--c1)' },
  { lang: 'python', label: 'pandas', bg: '#7D8DF0' },
  { lang: 'r', label: 'dplyr', bg: '#62BE74' },
];

/** The hovered block written in all three languages, straight from the generated code. */
export function TriBar() {
  const { state } = useStore();
  const id = state.hover;
  const gen = state.generated;
  if (!id || !gen) {
    return <div className="tribar"><span className="hint">Hover a block to see it in SQL, Python and R.</span></div>;
  }
  const snippet = (lang: Lang) => {
    let lines = gen[lang].lines.filter((l) => l.blocks.includes(id)).map((l) => l.text.trim());
    // a Join also tags the line that loads its table; show the step itself when there is one
    const steps = lines.filter((l) => !/read_csv\(|^library\(/.test(l));
    if (steps.length) lines = steps;
    const text = lines.join(' ').replace(/\s+/g, ' ').replace(/(\|>|%>%|,|;)$/, '').trim();
    return text.length > 90 ? `${text.slice(0, 88)}…` : text;
  };
  return (
    <div className="tribar" data-testid="tribar">
      {TRI.map((t, i) => (
        <span key={t.lang} style={{ display: 'contents' }}>
          {i > 0 && <span className="arrow">⇄</span>}
          <span className="lg" style={{ background: t.bg, color: t.fg ?? 'var(--ink)' }}>{t.label}</span>
          <span className="code" data-lang={t.lang}>{snippet(t.lang) || (t.lang === 'sql' ? 'none' : '—')}</span>
        </span>
      ))}
    </div>
  );
}
