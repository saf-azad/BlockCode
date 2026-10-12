import { usedTables } from '../ir';
import { run } from '../runtime';
import { effectiveLang, storedTables, useStore } from '../store';

export function useRun() {
  const { state, dispatch } = useStore();
  return async () => {
    const lang = effectiveLang(state);
    dispatch({ type: 'running' });
    try {
      const used = new Set(usedTables(state.program));
      const tables = storedTables(state).filter((t) => used.has(t.info.name));
      const result = await run(state.program, lang, tables,
        (text) => dispatch({ type: 'runnote', text }),
        (message) => dispatch({ type: 'toast', message }));
      dispatch({ type: 'ran', run: result });
      if (result.error?.block_id) dispatch({ type: 'focus', id: result.error.block_id });
    } catch (e) {
      dispatch({ type: 'ran', run: { target: lang, ok: false, tables: [], stdout: '', plots: [], error: { kind: 'Error', message: (e as Error).message, detail: '', line: null, block_id: null } } });
    }
  };
}
