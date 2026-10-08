import { effectiveLang, runIsStale, useStore } from '../store';
import { LANG_LABEL, type TableResult } from '../types';
import { useRun } from './run';

export function Output() {
  const { state, dispatch } = useStore();
  const run = state.run;
  const doRun = useRun();
  const lang = effectiveLang(state);
  if (!run) {
    if (state.running) return <div className="status running">Running {LANG_LABEL[lang]}…</div>;
    return (
      <div className="placeholder" style={{ marginTop: 18 }}>
        Press Run to see the result
        <button className="btn small" onClick={doRun}>Run {LANG_LABEL[lang]}</button>
      </div>
    );
  }
  const last = run.tables[run.tables.length - 1];
  const rows = last ? `${last.total_rows.toLocaleString()} row${last.total_rows === 1 ? '' : 's'}` : '';
  return (
    <div className={runIsStale(state) || state.running ? 'results stale' : 'results'}>
      <RunStatus />
      <ErrorCard />
      {run.tables.map((t, i) => <ResultTable key={t.name + i} t={t} showName={run.tables.length > 1} />)}
      {run.stdout && <div className="stdout" data-testid="stdout">{run.stdout}</div>}
      {run.plots.length > 0 && (
        <div className="inline-plots">
          {run.plots.map((png, i) => (
            <button key={i} className="inline-plot" title="Open in the Plot tab" onClick={() => dispatch({ type: 'tab', tab: 'plot' })}>
              <img src={`data:image/png;base64,${png}`} alt={`Figure ${i + 1}`} data-testid="output-plot" />
            </button>
          ))}
        </div>
      )}
      {!rows && !run.plots.length && !run.stdout && run.ok && <div className="status">Nothing to show: the program ran without making a table, a plot or any printing.</div>}
    </div>
  );
}

/** "Ran as Python · 5 rows · 1 plot", or what is happening right now. */
export function RunStatus() {
  const { state } = useStore();
  const run = state.run;
  const lang = effectiveLang(state);
  if (!run) return null;
  const last = run.tables[run.tables.length - 1];
  const rows = last ? `${last.total_rows.toLocaleString()} row${last.total_rows === 1 ? '' : 's'}` : '';
  let note = '';
  if (state.running) note = ' · updating…';
  else if (run.target !== lang) note = ' · the language has changed since, press Run again';
  else if (runIsStale(state)) note = ' · the blocks have changed since, fix the problems to update';
  return (
    <div className={`status${state.running ? ' running' : ''}`} data-testid="run-status">
      {run.ok ? `Ran as ${LANG_LABEL[run.target]}${rows ? ` · ${rows}` : ''}${run.plots.length ? ` · ${run.plots.length} plot${run.plots.length > 1 ? 's' : ''}` : ''}`
        : `${LANG_LABEL[run.target]} stopped with a problem`}
      {note}
    </div>
  );
}

const ERROR_TITLE: Record<string, string> = {
  NoR: 'R is not installed', Problem: 'Fix this block first', Timeout: 'Took too long', NoPlotDevice: "R couldn't save the plot",
};

export function ErrorCard() {
  const { state, dispatch } = useStore();
  const err = state.run?.error;
  if (!err) return null;
  const go = () => err.block_id && dispatch({ type: 'focus', id: err.block_id });
  return (
    <div className="errcard" role="button" tabIndex={0} data-testid="run-error" onClick={go} onKeyDown={(e) => e.key === 'Enter' && go()}>
      <h3>{ERROR_TITLE[err.kind] ?? `${err.kind}${err.line ? ` on line ${err.line}` : ''}`}</h3>
      <p>{err.message}</p>
      {err.detail && err.detail !== err.message && <code>{err.detail}</code>}
      {err.block_id && <span className="go">Show me the block →</span>}
    </div>
  );
}

function ResultTable({ t, showName }: { t: TableResult; showName: boolean }) {
  const numeric = t.columns.map((_, i) => t.rows.length > 0 && t.rows.every((r) => r[i] === null || typeof r[i] === 'number'));
  const fmt = (v: any) => (v === null ? 'empty' : typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(2) : String(v));
  return (
    <div className="result" data-testid="result">
      <table>
        {showName && <caption>{t.name}</caption>}
        <thead><tr><th aria-label="row" />{t.columns.map((c, j) => <th key={c} style={numeric[j] ? { textAlign: 'right' } : undefined}>{c}</th>)}</tr></thead>
        <tbody>
          {t.rows.map((r, i) => (
            <tr key={i}>
              <td className="i">{i + 1}</td>
              {r.map((v, j) => <td key={j} className={v === null ? 'null' : numeric[j] ? 'n' : ''}>{fmt(v)}</td>)}
            </tr>
          ))}
        </tbody>
        {t.total_rows > t.rows.length && <caption>Showing the first {t.rows.length} of {t.total_rows.toLocaleString()} rows.</caption>}
        {t.total_rows === 0 && <caption>No rows matched.</caption>}
      </table>
    </div>
  );
}
