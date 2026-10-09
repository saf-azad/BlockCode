import { api } from '../api';
import { effectiveLang, storedTables, useStore } from '../store';

export function useRun() {
  const { state, dispatch } = useStore();
  return async () => {
    const lang = effectiveLang(state);
    dispatch({ type: 'running' });
    try {
      const run = await api.run(state.program, lang, storedTables(state));
      dispatch({ type: 'ran', run });
      if (run.error?.block_id) dispatch({ type: 'focus', id: run.error.block_id });
    } catch (e) {
      dispatch({ type: 'ran', run: { target: lang, ok: false, tables: [], stdout: '', plots: [], error: { kind: 'Error', message: (e as Error).message, detail: '', line: null, block_id: null } } });
    }
  };
}
