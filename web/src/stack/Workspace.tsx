import { useDroppable } from '@dnd-kit/core';
import { useEffect } from 'react';
import { effectiveLang, useStore } from '../store';
import type { Lang } from '../types';
import { ScopeProvider } from './fields';
import { StatementList } from './Blocks';
import { useUpload } from '../sidebar/upload';
import { stackNames } from '../ir';

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
      const f = e.dataTransfer?.files?.[0];
      if (f) upload(f);
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
            {!blocks.length && (
              <p className="empty-hint">
                Drag a table or a <b>FROM</b> block here to start. Then snap steps like <b>WHERE</b> and{' '}
                <b>GROUP BY</b> underneath, or type code in the Code tab and the blocks will build themselves.
              </p>
            )}
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

function DropOverlay() {
  const { state } = useStore();
  const t = state.dropped;
  return (
    <div className="overlay" aria-live="polite">
      <h2>{t ? `Loaded ${t.name}` : 'Drop to load your CSV'}</h2>
      {t && (
        <>
          <div className="found">
            <div className="top"><span style={{ fontFamily: 'var(--head)', fontWeight: 800, fontSize: 16, color: 'var(--ink)' }}>Columns we found</span><span>{t.rows.toLocaleString()} rows</span></div>
            {t.columns.map((c) => (
              <div className="row" key={c.name}><span>{c.name}</span><span>{c.type}{c.empty ? ` · ${c.empty} empty` : ''}</span></div>
            ))}
          </div>
          <div style={{ fontSize: 15, color: 'var(--muted)' }}>
            Saved to {t.file.split('/')[0]}/ and loaded as the table <span style={{ fontFamily: 'var(--mono)' }}>{t.name}</span>.
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
