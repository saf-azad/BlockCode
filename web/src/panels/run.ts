import type { Dispatch } from 'react';
import { run } from '../runtime';
import { effectiveLang, useStore, type Action, type State } from '../store';

// Only the newest run's result is shown: an older one that finishes late is dropped.
let latest = 0;

export async function startRun(state: State, dispatch: Dispatch<Action>, auto = false) {
  const lang = effectiveLang(state);
  const seq = ++latest;
  dispatch({ type: 'running', auto });
  const note = (text: string | null) => { if (seq === latest) dispatch({ type: 'runnote', text }); };
  try {
    const result = await run(state.projectName, state.program, lang, note,
      (message) => dispatch({ type: 'toast', message }));
    if (seq !== latest) return;
    dispatch({ type: 'ran', run: result, auto });
    if (result.error?.block_id && !auto) dispatch({ type: 'focus', id: result.error.block_id });
  } catch (e) {
    if (seq !== latest) return;
    dispatch({ type: 'ran', auto, run: { target: lang, ok: false, tables: [], stdout: '', plots: [], code: state.generated?.[lang]?.code ?? '', error: { kind: 'Error', message: (e as Error).message, detail: '', line: null, block_id: null } } });
  }
}

export function useRun() {
  const { state, dispatch } = useStore();
  return () => startRun(state, dispatch);
}
