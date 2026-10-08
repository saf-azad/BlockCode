import { useEffect, useRef } from 'react';
import { api } from './api';
import { Panel } from './panels/Panel';
import { startRun } from './panels/run';
import { ErdPanel } from './sidebar/Erd';
import { Sidebar } from './sidebar/Sidebar';
import { DndProvider } from './stack/dnd';
import { Workspace } from './stack/Workspace';
import { effectiveLang, StoreProvider, useStore } from './store';
import { applyTheme } from './theme';
import { TopBar } from './TopBar';
import type { BlockSpec } from './types';

function useEngine() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);

  // load the project and the block specs
  useEffect(() => {
    const name = new URLSearchParams(window.location.search).get('project') || 'school';
    Promise.all([api.project(name), api.blocks()])
      .then(([project, specs]) => {
        const map: Record<string, BlockSpec> = {};
        for (const s of specs.blocks) map[s.type] = s;
        dispatch({ type: 'loaded', project, specs: map });
      })
      .catch((e) => dispatch({ type: 'error', message: `Can't reach the BlockCode engine: ${(e as Error).message}` }));
  }, [dispatch]);

  // regenerate all three languages when the blocks change
  useEffect(() => {
    if (!state.project) return;
    const t = setTimeout(() => {
      api.generateAll(state.projectName, state.program)
        .then((generated) => dispatch({ type: 'generated', generated }))
        .catch((e) => dispatch({ type: 'toast', message: (e as Error).message }));
    }, 120);
    return () => clearTimeout(t);
  }, [state.program, state.project, state.projectName, dispatch]);

  // save a moment after the last change
  useEffect(() => {
    if (state.saved !== 'unsaved' || !state.project) return;
    const t = setTimeout(() => {
      dispatch({ type: 'saved', status: 'saving' });
      api.saveProgram(state.projectName, state.program)
        .then(() => dispatch({ type: 'saved', status: 'saved' }))
        .catch(() => dispatch({ type: 'saved', status: 'unsaved' }));
    }, 900);
    return () => clearTimeout(t);
  }, [state.saved, state.program, state.project, state.projectName, dispatch]);

  // once you've run the program, keep its results in step with the blocks: re-run whenever
  // the code changes and has no problems (one run at a time, the newest wins)
  const stateRef = useRef(state);
  stateRef.current = state;
  const gen = state.generated?.[lang];
  useEffect(() => {
    const s = stateRef.current;
    if (!s.run || s.running || !gen) return;
    if (s.run.target === lang && s.run.code === gen.code) return;
    if (!gen.ok || gen.diagnostics.some((d) => d.severity === 'error')) return;
    const t = setTimeout(() => startRun(stateRef.current, dispatch, true), 350);
    return () => clearTimeout(t);
  }, [gen, lang, state.running, dispatch]);

  useEffect(() => applyTheme(lang), [lang]);

  useEffect(() => {
    if (!state.toast) return;
    const t = setTimeout(() => dispatch({ type: 'toast', message: null }), 3500);
    return () => clearTimeout(t);
  }, [state.toast, dispatch]);

  // undo / redo outside text fields
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        startRun(stateRef.current, dispatch);
        return;
      }
      const el = e.target as HTMLElement;
      if (el.closest('input, textarea, select, .cm-editor')) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        dispatch({ type: e.shiftKey ? 'redo' : 'undo' });
      }
      if (e.key === 'Escape') dispatch({ type: 'focus', id: null });
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [dispatch]);
}

function Shell() {
  const { state } = useStore();
  useEngine();
  return (
    <div className="app">
      <div className="chrome">
        <div className="dots"><span /><span /></div>
        <div className="rule" />
        <span className="name">BlockCode — {state.project?.title || 'loading'}</span>
        <div className="rule" />
      </div>
      <TopBar />
      {state.error ? (
        <div className="placeholder" style={{ margin: 40 }}>{state.error}<br />Start it with <code>uv run blockcode serve</code>.</div>
      ) : (
        <DndProvider>
          <div className="main">
            <Sidebar />
            <Workspace />
            <Panel />
          </div>
          {state.erdOpen && <ErdPanel />}
        </DndProvider>
      )}
      {state.toast && <div className="toast" role="status">{state.toast}</div>}
    </div>
  );
}

export function App() {
  return (
    <StoreProvider>
      <Shell />
    </StoreProvider>
  );
}
