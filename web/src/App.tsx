import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import { loadWorkspace, persistent, saveMeta } from './local';
import { Panel } from './panels/Panel';
import { ErdPanel } from './sidebar/Erd';
import { Sidebar } from './sidebar/Sidebar';
import { DndProvider } from './stack/dnd';
import { Workspace } from './stack/Workspace';
import { effectiveLang, StoreProvider, UNTITLED, useStore } from './store';
import { applyTheme } from './theme';
import { TopBar } from './TopBar';
import type { BlockSpec } from './types';

function useEngine() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  // the block specs from the server, the workspace from this browser
  useEffect(() => {
    Promise.all([api.blocks(), api.health().catch(() => null), loadWorkspace(), persistent()])
      .then(([specs, health, saved, canSave]) => {
        const map: Record<string, BlockSpec> = {};
        for (const s of specs.blocks) map[s.type] = s;
        const project = {
          name: 'local',
          title: saved.meta?.title ?? '',
          tables: saved.tables.map((t) => t.info),
          program: saved.meta?.program ?? { blocks: [] },
        };
        const files = Object.fromEntries(saved.tables.map((t) => [t.info.name, t.data]));
        dispatch({ type: 'loaded', project, files, specs: map, rReady: !!health?.r, canSave });
      })
      .catch((e) => dispatch({ type: 'error', message: (e as Error).message }));
  }, [dispatch, attempt]);

  // regenerate all three languages when the blocks, tables or title change
  const tables = state.project?.tables;
  const title = state.project?.title ?? '';
  useEffect(() => {
    if (!tables) return;
    const t = setTimeout(() => {
      api.generateAll(state.program, tables, title || UNTITLED)
        .then((generated) => dispatch({ type: 'generated', generated }))
        .catch((e) => dispatch({ type: 'toast', message: (e as Error).message }));
    }, 120);
    return () => clearTimeout(t);
  }, [state.program, tables, title, dispatch]);

  // keep the workspace in this browser a moment after the last change
  useEffect(() => {
    if (state.saved !== 'unsaved' || !state.project) return;
    const t = setTimeout(() => {
      dispatch({ type: 'saved', status: 'saving' });
      saveMeta({ title, program: state.program, order: (tables ?? []).map((x) => x.name) })
        .finally(() => dispatch({ type: 'saved', status: 'saved' }));
    }, 500);
    return () => clearTimeout(t);
  }, [state.saved, state.program, state.project, tables, title, dispatch]);

  // save straight away when the tab is hidden or closed, so an edit in the last half second
  // before a reload isn't lost
  useEffect(() => {
    if (!state.project) return;
    const flush = () => {
      if (state.saved === 'unsaved') {
        saveMeta({ title, program: state.program, order: (tables ?? []).map((x) => x.name) });
      }
    };
    const onHide = () => { if (document.visibilityState === 'hidden') flush(); };
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', onHide);
    return () => {
      window.removeEventListener('pagehide', flush);
      document.removeEventListener('visibilitychange', onHide);
    };
  }, [state.saved, state.program, state.project, tables, title]);

  useEffect(() => applyTheme(lang), [lang]);

  useEffect(() => {
    if (!state.toast) return;
    const t = setTimeout(() => dispatch({ type: 'toast', message: null }), 4500);
    return () => clearTimeout(t);
  }, [state.toast, dispatch]);

  // undo / redo outside text fields
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest('input, textarea, select, .cm-editor')) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        dispatch({ type: e.shiftKey ? 'redo' : 'undo' });
      }
      if (e.key === 'Escape') dispatch({ type: 'focus', id: null });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dispatch]);

  return retry;
}

function SmallScreenNote() {
  const [open, setOpen] = useState(() => typeof window !== 'undefined' && window.innerWidth < 900);
  if (!open) return null;
  return (
    <div className="small-screen" role="note">
      <span>BlockCode is made for a laptop or desktop. You can look around here, but dragging blocks works best with a mouse.</span>
      <button className="btn tiny" onClick={() => setOpen(false)}>OK</button>
    </div>
  );
}

function Shell() {
  const { state } = useStore();
  const retry = useEngine();
  const loading = !state.project && !state.error;
  return (
    <div className="app">
      <div className="chrome">
        <div className="dots"><span /><span /></div>
        <div className="rule" />
        <span className="name">BlockCode{state.project ? ` — ${state.project.title || UNTITLED}` : ''}</span>
        <div className="rule" />
      </div>
      <TopBar />
      {state.error && !state.project ? (
        <div className="placeholder" style={{ margin: 40 }} role="alert">
          <b style={{ color: 'var(--ink)' }}>BlockCode couldn't start.</b>
          <span>{state.error}</span>
          <button className="btn small" onClick={retry}>Try again</button>
        </div>
      ) : loading ? (
        <div className="placeholder" style={{ margin: 40, animation: 'pulse 1.2s infinite' }}>Loading…</div>
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
      <SmallScreenNote />
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
