// R in the browser: webR (which runs R in its own worker). Packages the program loads with
// library() are installed from the webR package repository the first time they're needed.
import type { Job, Raw } from '../types';
import { RuntimeLoadError, type Status } from './errors';

/* eslint-disable @typescript-eslint/no-explicit-any */
let webR: any = null;
let ready: Promise<void> | null = null;
let queue: Promise<unknown> = Promise.resolve();
let installed: Set<string> | null = null;
let runs = 0;
const fetched = new Map<string, string>();
const PLOT = { width: 660, height: 440 }; // the plot size (webR draws at twice this, for sharp screens)

const q = (s: string) => JSON.stringify(s); // an R string literal

function start(url: string, repo: string, onStatus: Status | null): Promise<void> {
  if (ready) return ready;
  ready = (async () => {
    onStatus?.('Starting R in your browser…');
    const { WebR } = await import(/* @vite-ignore */ url);
    webR = new WebR({ baseUrl: url.slice(0, url.lastIndexOf('/') + 1), repoUrl: repo, interactive: false });
    await webR.init();
    installed = await listInstalled();
  })().catch((e) => {
    stop();
    throw new RuntimeLoadError('R', (e as Error).message ?? String(e));
  });
  return ready;
}

function stop() {
  try { webR?.close(); } catch { /* already gone */ }
  webR = null;
  ready = null;
  installed = null;
  fetched.clear();
}

/** Start loading R now (and the packages this code uses), so the first run doesn't wait. */
export function warmR(url: string, repo: string, code: string) {
  queue = queue.then(() => start(url, repo, null).then(() => install(code, null))).catch(() => undefined);
}

async function install(code: string, onStatus: Status | null) {
  const wanted = [...code.matchAll(/^\s*library\(\s*["']?([\w.]+)["']?\s*\)/gm)].map((m) => m[1]);
  const missing = [...new Set(wanted)].filter((p) => !installed!.has(p));
  if (!missing.length) return;
  onStatus?.(`Installing ${missing.join(', ')} for R (first run only)…`);
  let why = '';
  try {
    await webR.installPackages(missing, { quiet: true });
  } catch (e) {
    why = `: ${(e as Error).message}`;
  }
  // a package that can't be downloaded is only a warning to webR: check what arrived
  installed = await listInstalled();
  const still = missing.filter((p) => !installed!.has(p));
  if (still.length) throw new RuntimeLoadError('R', `couldn't install ${still.join(', ')}${why}`);
}

async function listInstalled(): Promise<Set<string>> {
  return new Set(await (await webR.evalR('rownames(installed.packages())')).toArray());
}

async function mkdirs(path: string) {
  let at = '';
  for (const part of path.split('/').filter(Boolean)) {
    at += `/${part}`;
    try { await webR.FS.mkdir(at); } catch { /* exists */ }
  }
}

async function readText(path: string): Promise<string | null> {
  try {
    return new TextDecoder().decode(await webR.FS.readFile(path));
  } catch {
    return null;
  }
}

async function toPng(img: ImageBitmap): Promise<string> {
  const canvas = new OffscreenCanvas(img.width, img.height);
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, img.width, img.height);
  ctx.drawImage(img, 0, 0);
  const bytes = new Uint8Array(await (await canvas.convertToBlob({ type: 'image/png' })).arrayBuffer());
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function run(job: Job, onStatus: Status): Promise<Raw> {
  await install(job.code, onStatus);
  const dir = `/home/web_user/${job.project}`;
  for (const f of job.files) {
    const at = `${dir}/${f.path}`;
    if (fetched.get(at) === f.version) continue;
    const res = await fetch(f.url);
    if (!res.ok) throw new RuntimeLoadError('R', `couldn't fetch ${f.path} (${res.status})`);
    await mkdirs(at.slice(0, at.lastIndexOf('/')));
    await webR.FS.writeFile(at, new Uint8Array(await res.arrayBuffer()));
    fetched.set(at, f.version);
  }
  const out = `/tmp/bc/run${++runs}`;
  await mkdirs(out);
  const enc = new TextEncoder();
  await webR.FS.writeFile(`${out}/program.R`, enc.encode(job.code));
  await webR.FS.writeFile(`${out}/h.R`, enc.encode(job.harness));
  onStatus(null);

  const shelter = await new webR.Shelter();
  // a fresh start each run: no variables left over from the last one (webR opens a new plot
  // device for every capture)
  const capture = shelter.captureR(
    `rm(list = ls(all.names = TRUE, envir = globalenv()), envir = globalenv())
     setwd(${q(dir)})
     .bc_job <- c(${q(out)}, ${q(job.names.join(','))}, ${q(`${out}/program.R`)}, "canvas")
     source(${q(`${out}/h.R`)})`,
    { captureGraphics: { ...PLOT, bg: 'white' }, throwJsException: false },
  ) as Promise<{ output: { type: string; data: unknown }[]; images: ImageBitmap[] }>;
  // too long: interrupt R; if it can't be (only a cross-origin isolated page can) or doesn't
  // stop, throw it away (it starts again next run)
  let timedOut = false;
  const captured = await new Promise<Awaited<typeof capture> | null>((resolve, reject) => {
    let kill: ReturnType<typeof setTimeout> | undefined;
    const timer = setTimeout(() => {
      timedOut = true;
      if (self.crossOriginIsolated) webR.interrupt();
      kill = setTimeout(() => { stop(); resolve(null); }, self.crossOriginIsolated ? 2000 : 0);
    }, job.timeout * 1000);
    const settle = () => { clearTimeout(timer); clearTimeout(kill); };
    capture.then((c) => { settle(); resolve(timedOut ? null : c); },
      (e) => { settle(); if (timedOut) resolve(null); else reject(e); });
  });
  if (!captured) return { stdout: '', timed_out: true, files: {}, plots: [] };
  shelter.purge().catch(() => undefined);
  const stdout = captured.output.filter((o) => o.type === 'stdout').map((o) => `${o.data}\n`).join('');
  const files: Record<string, string> = {};
  const names = ['error.txt', 'pages.txt', 'nodevice.txt', ...job.names.flatMap((n) => [`table_${n}.csv`, `rows_${n}.txt`])];
  for (const n of names) {
    const text = await readText(`${out}/${n}`);
    if (text !== null) files[n] = text;
  }
  const plots = await Promise.all(captured.images.map(toPng));
  return { stdout, timed_out: false, files, plots };
}

export function runR(job: Job, url: string, repo: string, onStatus: Status): Promise<Raw> {
  const go = async () => {
    await start(url, repo, onStatus);
    return run(job, onStatus);
  };
  const next = queue.then(go, go);
  queue = next.catch(() => undefined);
  return next;
}
