import { api } from '../api';
import { effectiveLang, useStore, type Action, type State } from '../store';
import type { Dispatch } from 'react';

// Only the newest run's result is shown: an older one that finishes late is dropped.
let latest = 0;

export async function startRun(state: State, dispatch: Dispatch<Action>, auto = false) {
  const lang = effectiveLang(state);
  const seq = ++latest;
  dispatch({ type: 'running' });
  try {
    const run = await api.run(state.projectName, state.program, lang);
    if (seq !== latest) return;
    dispatch({ type: 'ran', run, auto });
    if (run.error?.block_id && !auto) dispatch({ type: 'focus', id: run.error.block_id });
  } catch (e) {
    if (seq !== latest) return;
    dispatch({ type: 'ran', auto, run: { target: lang, ok: false, tables: [], stdout: '', plots: [], code: state.generated?.[lang]?.code ?? '', error: { kind: 'Error', message: (e as Error).message, detail: '', line: null, block_id: null } } });
  }
}

export function useRun() {
  const { state, dispatch } = useStore();
  return () => startRun(state, dispatch);
}
