// Runs Python jobs in the Pyodide worker: one at a time, stopping any that run too long.
import type { Job, Raw } from '../types';
import type { FromWorker, ToWorker } from './pyworker';
import { RuntimeLoadError, type Status } from './errors';

let worker: Worker | null = null;
let loaded: Promise<void> | null = null;
let nextId = 1;
let queue: Promise<unknown> = Promise.resolve();
const waiting = new Map<number, (m: FromWorker) => void>();

function start(url: string): Promise<void> {
  if (loaded) return loaded;
  worker = new Worker(new URL('./pyworker.ts', import.meta.url), { type: 'module' });
  worker.onmessage = (e: MessageEvent<FromWorker>) => waiting.get(e.data.id)?.(e.data);
  worker.onerror = (e) => {
    for (const fn of waiting.values()) fn({ id: 0, type: 'error', message: e.message || 'The Python worker failed.' });
  };
  const id = nextId++;
  loaded = new Promise<void>((resolve, reject) => {
    waiting.set(id, (m) => {
      if (m.type === 'loaded') { waiting.delete(id); resolve(); }
      if (m.type === 'error') { waiting.delete(id); reject(new RuntimeLoadError('Python', m.message)); }
      if (m.type === 'status') statusFn?.(m.text);
    });
  }).catch((e) => { stop(); throw e; });
  worker.postMessage({ id, type: 'load', url } satisfies ToWorker);
  return loaded;
}

let statusFn: Status | null = null;

function stop() {
  worker?.terminate();
  worker = null;
  loaded = null;
}

/** Start loading Python now, so the first run doesn't wait for it. */
export function warmPython(url: string) {
  start(url).catch(() => undefined);
}

export function runPython(job: Job, url: string, onStatus: Status): Promise<Raw> {
  const go = async (): Promise<Raw> => {
    statusFn = onStatus;
    await start(url);
    const id = nextId++;
    return new Promise<Raw>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      const done = (v: Raw | Error) => {
        if (timer) clearTimeout(timer);
        waiting.delete(id);
        if (v instanceof Error) reject(v); else resolve(v);
      };
      waiting.set(id, (m) => {
        if (m.type === 'status') onStatus(m.text);
        if (m.type === 'started') {
          onStatus(null);
          // a program that never stops can only be stopped by throwing the worker away
          timer = setTimeout(() => { stop(); done({ stdout: '', timed_out: true, data: null }); }, job.timeout * 1000);
        }
        if (m.type === 'done') done({ stdout: m.stdout, timed_out: false, data: m.data });
        if (m.type === 'error') { stop(); done(m.load ? new RuntimeLoadError('Python', m.message) : new Error(m.message)); }
      });
      worker!.postMessage({ id, type: 'run', job } satisfies ToWorker);
    });
  };
  const next = queue.then(go, go);
  queue = next.catch(() => undefined);
  return next;
}
