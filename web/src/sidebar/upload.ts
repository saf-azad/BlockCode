import { api } from '../api';
import { useStore } from '../store';

/** Upload a CSV, show what we found, and refresh the tables. */
export function useUpload() {
  const { state, dispatch } = useStore();
  return async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.csv')) {
      dispatch({ type: 'dropping', on: false });
      dispatch({ type: 'toast', message: 'Only .csv files can be dropped here.' });
      return;
    }
    try {
      const { table } = await api.upload(state.projectName, file);
      const project = await api.project(state.projectName);
      dispatch({ type: 'tables', tables: project.tables });
      dispatch({ type: 'dropped', table });
      setTimeout(() => dispatch({ type: 'dropped', table: null }), 3200);
    } catch (e) {
      dispatch({ type: 'dropping', on: false });
      dispatch({ type: 'toast', message: (e as Error).message });
    }
  };
}
