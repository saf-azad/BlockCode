import { api } from '../api';
import { gzip, saveTable } from '../local';
import { useStore } from '../store';

const MAX_BYTES = 10 * 1024 * 1024;
let hideTimer: ReturnType<typeof setTimeout> | undefined;

/** Read CSVs: the server works out the columns, the file itself is kept in this browser. */
export function useUpload() {
  const { dispatch } = useStore();
  return async (input: File | File[] | FileList) => {
    const files = input instanceof File ? [input] : Array.from(input);
    dispatch({ type: 'dropping', on: false });
    for (const file of files) {
      if (/\.(xlsx?|xlsm|ods|numbers)$/i.test(file.name)) {
        dispatch({ type: 'toast', message: `${file.name} is a spreadsheet. Save it as CSV first (File → Save As → CSV).` });
        continue;
      }
      if (!/\.(csv|tsv|txt)$/i.test(file.name)) {
        dispatch({ type: 'toast', message: `${file.name} isn't a CSV file. Drop a .csv (or .tsv) file.` });
        continue;
      }
      if (file.size > MAX_BYTES) {
        dispatch({ type: 'toast', message: `${file.name} is too big (10 MB max). Try a smaller extract of the data.` });
        continue;
      }
      dispatch({ type: 'uploading', delta: 1 });
      try {
        const data = await gzip(file);
        const { table, notes } = await api.inspect(data, file.name);
        await saveTable({ info: table, data });
        dispatch({ type: 'addTable', table, data });
        dispatch({ type: 'dropped', dropped: { table, notes } });
        clearTimeout(hideTimer);
        hideTimer = setTimeout(() => dispatch({ type: 'dropped', dropped: null }), notes.length ? 6500 : 3500);
      } catch (e) {
        dispatch({ type: 'toast', message: `${file.name}: ${(e as Error).message}` });
      } finally {
        dispatch({ type: 'uploading', delta: -1 });
      }
    }
  };
}
