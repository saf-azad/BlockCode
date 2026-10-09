import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react';
import { hasPythonOnly } from './ir';
import type { StoredTable } from './local';
import type { BlockSpec, Generated, Lang, ParseResult, Program, Project, RunResult, TableInfo } from './types';

export type Tab = 'code' | 'output' | 'plot' | 'problems';

export interface Editing {
  lang: Lang;
  text: string;
  parse: ParseResult | null; // last parse of ``text`` (null while waiting)
}

export const UNTITLED = 'Untitled analysis';

export interface Dropped {
  table: TableInfo;
  notes: string[];
}

export interface State {
  project: Project | null; // the workspace: title, tables (schemas) and program
  files: Record<string, Blob>; // each table's CSV as uploaded (gzipped), by table name
  specs: Record<string, BlockSpec>;
  program: Program;
  history: Program[];
  future: Program[];
  lang: Lang;
  generated: Record<Lang, Generated> | null;
  hover: string | null;
  focus: string | null;
  tab: Tab;
  run: RunResult | null;
  running: boolean;
  editing: Editing | null;
  saved: 'saved' | 'saving' | 'unsaved';
  rReady: boolean; // R can run on this server
  canSave: boolean; // this browser keeps the workspace between visits
  dropping: boolean;
  uploading: number; // files being read right now
  dropped: Dropped | null;
  erdOpen: boolean;
  toast: string | null;
  error: string | null;
}

export const initialState: State = {
  project: null,
  files: {},
  specs: {},
  program: { blocks: [] },
  history: [],
  future: [],
  lang: 'sql',
  generated: null,
  hover: null,
  focus: null,
  tab: 'code',
  run: null,
  running: false,
  editing: null,
  saved: 'saved',
  rReady: true,
  canSave: true,
  dropping: false,
  uploading: 0,
  dropped: null,
  erdOpen: false,
  toast: null,
  error: null,
};

export type Action =
  | { type: 'loaded'; project: Project; files: Record<string, Blob>; specs: Record<string, BlockSpec>; rReady: boolean; canSave: boolean }
  | { type: 'addTable'; table: TableInfo; data: Blob }
  | { type: 'removeTable'; name: string }
  | { type: 'title'; title: string }
  | { type: 'reset' }
  | { type: 'uploading'; delta: number }
  | { type: 'program'; program: Program; fromCode?: boolean }
  | { type: 'update'; fn: (p: Program) => Program }
  | { type: 'undo' }
  | { type: 'redo' }
  | { type: 'lang'; lang: Lang }
  | { type: 'generated'; generated: Record<Lang, Generated> }
  | { type: 'hover'; id: string | null }
  | { type: 'focus'; id: string | null }
  | { type: 'tab'; tab: Tab }
  | { type: 'running' }
  | { type: 'ran'; run: RunResult }
  | { type: 'edit'; text: string }
  | { type: 'parsed'; parse: ParseResult; text: string }
  | { type: 'tidy' }
  | { type: 'saved'; status: State['saved'] }
  | { type: 'dropping'; on: boolean }
  | { type: 'dropped'; dropped: Dropped | null }
  | { type: 'erd'; open: boolean }
  | { type: 'toast'; message: string | null }
  | { type: 'error'; message: string | null };

/** The language actually shown: SQL is off while Python/R-only blocks are on the workspace. */
export function effectiveLang(s: Pick<State, 'lang' | 'program'>): Lang {
  return s.lang === 'sql' && hasPythonOnly(s.program) ? 'python' : s.lang;
}

const HISTORY = 100;

export function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'loaded':
      return {
        ...s, project: a.project, files: a.files, specs: a.specs, rReady: a.rReady, canSave: a.canSave, program: a.project.program,
        history: [], future: [], error: null,
      };
    case 'addTable': {
      if (!s.project) return s;
      const tables = [...s.project.tables.filter((t) => t.name !== a.table.name), a.table];
      return { ...s, project: { ...s.project, tables }, files: { ...s.files, [a.table.name]: a.data }, saved: 'unsaved' };
    }
    case 'removeTable': {
      if (!s.project) return s;
      const files = { ...s.files };
      delete files[a.name];
      return { ...s, project: { ...s.project, tables: s.project.tables.filter((t) => t.name !== a.name) }, files, saved: 'unsaved', run: null };
    }
    case 'title':
      return s.project ? { ...s, project: { ...s.project, title: a.title }, saved: 'unsaved' } : s;
    case 'reset':
      return {
        ...s, project: s.project ? { ...s.project, title: '', tables: [], program: { blocks: [] } } : s.project,
        files: {}, program: { blocks: [] }, history: [], future: [], run: null, editing: null, hover: null, focus: null,
        tab: 'code', lang: 'sql', saved: 'unsaved', erdOpen: false,
      };
    case 'uploading':
      return { ...s, uploading: Math.max(0, s.uploading + a.delta) };
    case 'program': {
      if (a.program === s.program) return s;
      return {
        ...s,
        program: a.program,
        history: [...s.history, s.program].slice(-HISTORY),
        future: [],
        saved: 'unsaved',
        // editing blocks by hand takes over from typed code
        editing: a.fromCode ? s.editing : null,
      };
    }
    case 'update':
      return reducer(s, { type: 'program', program: a.fn(s.program) });
    case 'undo': {
      const prev = s.history[s.history.length - 1];
      if (!prev) return s;
      return { ...s, program: prev, history: s.history.slice(0, -1), future: [s.program, ...s.future], saved: 'unsaved', editing: null };
    }
    case 'redo': {
      const next = s.future[0];
      if (!next) return s;
      return { ...s, program: next, future: s.future.slice(1), history: [...s.history, s.program], saved: 'unsaved', editing: null };
    }
    case 'lang':
      return { ...s, lang: a.lang, editing: null };
    case 'generated':
      return { ...s, generated: a.generated };
    case 'hover':
      return s.hover === a.id ? s : { ...s, hover: a.id };
    case 'focus':
      return { ...s, focus: a.id };
    case 'tab':
      return { ...s, tab: a.tab };
    case 'running':
      return { ...s, running: true };
    case 'ran':
      return {
        ...s, running: false, run: a.run,
        tab: a.run.ok && a.run.plots.length && !a.run.tables.length && !a.run.stdout ? 'plot' : 'output',
      };
    case 'edit': {
      const lang = effectiveLang(s);
      return { ...s, editing: { lang, text: a.text, parse: null } };
    }
    case 'parsed':
      if (!s.editing || s.editing.text !== a.text) return s;
      return { ...s, editing: { ...s.editing, parse: a.parse } };
    case 'tidy':
      return { ...s, editing: null };
    case 'saved':
      return { ...s, saved: a.status };
    case 'dropping':
      return { ...s, dropping: a.on };
    case 'dropped':
      return { ...s, dropped: a.dropped, dropping: false };
    case 'erd':
      return { ...s, erdOpen: a.open };
    case 'toast':
      return { ...s, toast: a.message };
    case 'error':
      return { ...s, error: a.message };
    default:
      return s;
  }
}

const Ctx = createContext<{ state: State; dispatch: Dispatch<Action> } | null>(null);

export function StoreProvider({ children, initial }: { children: ReactNode; initial?: Partial<State> }) {
  const [state, dispatch] = useReducer(reducer, { ...initialState, ...initial });
  return <Ctx.Provider value={{ state, dispatch }}>{children}</Ctx.Provider>;
}

export function useStore() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useStore outside StoreProvider');
  return ctx;
}

/** Every table with its CSV, ready to send with a run or export. */
export function storedTables(s: Pick<State, 'project' | 'files'>): StoredTable[] {
  return (s.project?.tables ?? []).filter((t) => s.files[t.name]).map((t) => ({ info: t, data: s.files[t.name] }));
}

/** Shorthand: change the program. */
export function useEdit() {
  const { dispatch } = useStore();
  return (fn: (p: Program) => Program) => dispatch({ type: 'update', fn });
}
