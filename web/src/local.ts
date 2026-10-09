// The visitor's workspace, kept in their own browser (IndexedDB): the title, the blocks and
// each table's CSV exactly as uploaded (gzipped). The server keeps nothing, so this is the only
// copy. If the browser won't store anything (private windows, blocked storage) the workspace
// still works for as long as the tab is open.
import type { Program, TableInfo } from './types';

export interface Meta {
  title: string;
  program: Program;
  order: string[]; // table names, in the order they were added
}

export interface StoredTable {
  info: TableInfo;
  data: Blob;
}

const DB_NAME = 'blockcode';
const STORE = 'workspace';
const META = 'meta';
const TABLE = (name: string) => `table:${name}`;

let dbPromise: Promise<IDBDatabase | null> | null = null;

function open(): Promise<IDBDatabase | null> {
  if (!dbPromise) {
    dbPromise = new Promise((resolve) => {
      try {
        if (typeof indexedDB === 'undefined') return resolve(null);
        const req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = () => req.result.createObjectStore(STORE);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(null);
        req.onblocked = () => resolve(null);
      } catch {
        resolve(null);
      }
    });
  }
  return dbPromise;
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest | void): Promise<T | undefined> {
  const db = await open();
  if (!db) return undefined;
  return new Promise((resolve) => {
    try {
      const t = db.transaction(STORE, mode);
      const req = fn(t.objectStore(STORE));
      t.oncomplete = () => resolve(req ? (req.result as T) : undefined);
      t.onerror = () => resolve(undefined);
      t.onabort = () => resolve(undefined);
    } catch {
      resolve(undefined);
    }
  });
}

/** Can this browser keep the workspace between visits? */
export async function persistent(): Promise<boolean> {
  return (await open()) !== null;
}

export async function loadWorkspace(): Promise<{ meta: Meta | null; tables: StoredTable[] }> {
  const meta = (await tx<Meta>('readonly', (s) => s.get(META))) ?? null;
  const tables: StoredTable[] = [];
  for (const name of meta?.order ?? []) {
    const t = await tx<StoredTable>('readonly', (s) => s.get(TABLE(name)));
    if (t?.info && t.data) tables.push(t);
  }
  return { meta, tables };
}

export function saveMeta(meta: Meta): Promise<unknown> {
  return tx('readwrite', (s) => s.put(meta, META));
}

export function saveTable(t: StoredTable): Promise<unknown> {
  return tx('readwrite', (s) => s.put(t, TABLE(t.info.name)));
}

export function deleteTable(name: string): Promise<unknown> {
  return tx('readwrite', (s) => s.delete(TABLE(name)));
}

export function clearWorkspace(): Promise<unknown> {
  return tx('readwrite', (s) => s.clear());
}

/** Gzip a file before it goes to the server (CSVs shrink 5-10×); plain if the browser can't. */
export async function gzip(blob: Blob): Promise<Blob> {
  try {
    if (typeof CompressionStream === 'undefined') return blob;
    const zipped = await new Response(blob.stream().pipeThrough(new CompressionStream('gzip'))).blob();
    return new Blob([zipped], { type: 'application/gzip' });
  } catch {
    return blob;
  }
}
