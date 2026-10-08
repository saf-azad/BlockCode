import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { useRun } from './panels/run';
import { effectiveLang, useStore } from './store';
import { LANG_LABEL } from './types';

const EXT = { sql: '.sql', python: '.py', r: '.qmd' };

export function TopBar() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);
  const run = useRun();
  const [menu, setMenu] = useState(false);
  const [examples, setExamples] = useState<{ name: string; title: string }[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.examples().then((r) => setExamples(r.examples)).catch(() => undefined);
  }, []);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenu(false);
    };
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, []);

  const doExport = async () => {
    try {
      const blob = await api.export(state.projectName, state.program, lang);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${state.projectName}-${lang}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      dispatch({ type: 'toast', message: `Exported ${EXT[lang]} with its data, ready to run on its own.` });
    } catch (e) {
      dispatch({ type: 'toast', message: (e as Error).message });
    }
  };

  const load = async (name: string) => {
    setMenu(false);
    const program = await api.example(name);
    dispatch({ type: 'program', program });
    dispatch({ type: 'focus', id: null });
  };

  return (
    <div className="topbar">
      <div className="left">
        <span className="title">{state.project?.title || state.projectName}</span>
        <span className="tag">{state.projectName === 'school' ? 'school sample' : state.projectName}</span>
        <span className="status" data-testid="saved">{state.saved === 'saved' ? 'Saved' : state.saved === 'saving' ? 'Saving…' : 'Edited'}</span>
        <button className="btn tiny" disabled={!state.history.length} onClick={() => dispatch({ type: 'undo' })} title="Undo (Ctrl+Z)">Undo</button>
        <button className="btn tiny" disabled={!state.future.length} onClick={() => dispatch({ type: 'redo' })} title="Redo (Ctrl+Shift+Z)">Redo</button>
      </div>
      <div className="right">
        <div className="menu-wrap" ref={ref}>
          <button className="btn small" onClick={() => setMenu(!menu)} aria-expanded={menu}>Examples ▾</button>
          {menu && (
            <div className="menu" role="menu">
              <div className="label">Load an example</div>
              {examples.map((ex) => <button key={ex.name} role="menuitem" onClick={() => load(ex.name)}>{ex.title}</button>)}
              <div className="label">Start again</div>
              <button role="menuitem" onClick={() => { setMenu(false); dispatch({ type: 'program', program: { blocks: [] } }); }}>Empty workspace</button>
            </div>
          )}
        </div>
        <button className="btn primary" onClick={run} disabled={state.running} data-testid="run">
          <svg width="11" height="11" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1l7 4-7 4z" fill="currentColor" /></svg>
          {state.running ? 'Running…' : `Run ${LANG_LABEL[lang]}`}
        </button>
        <button className="btn" onClick={doExport} data-testid="export">Export {EXT[lang]}</button>
      </div>
    </div>
  );
}
