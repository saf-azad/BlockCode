/// <reference lib="webworker" />
// Python in the browser: a Web Worker running Pyodide, so a long program never freezes the page.
// It runs the server's harness around the learner's code, exactly as the server would.
import type { Job } from '../types';

export type ToWorker =
  | { id: number; type: 'load'; url: string }
  | { id: number; type: 'run'; job: Job };

export type FromWorker =
  | { id: number; type: 'status'; text: string }
  | { id: number; type: 'started' } // the program itself has started (time it from here)
  | { id: number; type: 'done'; stdout: string; data: Record<string, unknown> | null }
  | { id: number; type: 'loaded' }
  | { id: number; type: 'error'; message: string; load?: boolean }; // load: Python itself or a package didn't arrive

declare const self: DedicatedWorkerGlobalScope;

class LoadError extends Error {}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let py: any = null;
const fetched = new Map<string, string>(); // file path in the FS -> version written there
const post = (m: FromWorker) => self.postMessage(m);

async function load(url: string, id: number) {
  if (py) return;
  post({ id, type: 'status', text: 'Starting Python in your browser…' });
  const mod = await import(/* @vite-ignore */ url);
  py = await mod.loadPyodide({ indexURL: url.slice(0, url.lastIndexOf('/') + 1) });
}

function mkdirs(path: string) {
  let at = '';
  for (const part of path.split('/').filter(Boolean)) {
    at += `/${part}`;
    if (!py.FS.analyzePath(at).exists) py.FS.mkdir(at);
  }
}

async function run(job: Job, id: number) {
  const dir = `/work/${job.project}`;
  for (const f of job.files) {
    const at = `${dir}/${f.path}`;
    if (fetched.get(at) === f.version) continue;
    const res = await fetch(f.url);
    if (!res.ok) throw new LoadError(`Couldn't fetch ${f.path} (${res.status})`);
    mkdirs(at.slice(0, at.lastIndexOf('/')));
    py.FS.writeFile(at, new Uint8Array(await res.arrayBuffer()));
    fetched.set(at, f.version);
  }
  // pandas, matplotlib, ... : only what the program imports, downloaded the first time
  const failed: string[] = [];
  await py.loadPackagesFromImports(job.code, {
    messageCallback: (m: string) => { if (/^Loading /.test(m)) post({ id, type: 'status', text: `${m} (first run only)…` }); },
    errorCallback: (m: string) => failed.push(m),
  });
  if (failed.length) throw new LoadError(failed.join('\n'));
  mkdirs('/tmp/bc');
  py.FS.writeFile('/tmp/bc/program.py', job.code);
  if (py.FS.analyzePath('/tmp/bc/result.json').exists) py.FS.unlink('/tmp/bc/result.json');
  let stdout = '';
  const decoder = new TextDecoder();
  py.setStdout({ write: (buf: Uint8Array) => { stdout += decoder.decode(buf, { stream: true }); return buf.length; } });
  py.setStderr({ write: (buf: Uint8Array) => buf.length });
  const globals = py.toPy({ __name__: '__main__' });
  py.runPython(`import os, sys\nos.chdir(${JSON.stringify(dir)})\nsys.argv = ${JSON.stringify(['h.py', '/tmp/bc/program.py', '/tmp/bc/result.json', JSON.stringify(job.names)])}`, { globals });
  post({ id, type: 'started' });
  py.runPython(job.harness, { globals: py.toPy({ __name__: '__main__' }) });
  globals.destroy();
  const out = py.FS.analyzePath('/tmp/bc/result.json').exists ? JSON.parse(py.FS.readFile('/tmp/bc/result.json', { encoding: 'utf8' })) : null;
  post({ id, type: 'done', stdout, data: out });
}

self.onmessage = async (e: MessageEvent<ToWorker>) => {
  const m = e.data;
  try {
    if (m.type === 'load') {
      await load(m.url, m.id);
      post({ id: m.id, type: 'loaded' });
    } else {
      await run(m.job, m.id);
    }
  } catch (err) {
    post({ id: m.id, type: 'error', message: (err as Error).message ?? String(err), load: m.type === 'load' || err instanceof LoadError });
  }
};
