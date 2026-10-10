import { effectiveLang, useStore } from '../store';
import { LANG_LABEL, type TableResult } from '../types';
import { useRun } from './run';

export function Output() {
  const { state, dispatch } = useStore();
  const run = state.run;
  const doRun = useRun();
  const lang = effectiveLang(state);
  if (state.running) return <div className="status" style={{ animation: 'pulse 1s infinite' }}>Running {LANG_LABEL[lang]}…</div>;
  if (!run) {
    if (!state.program.blocks.length) {
      return <div className="placeholder" style={{ marginTop: 18 }}>Add some blocks, then press Run to see the result here.</div>;
    }
    if (lang === 'r' && !state.rReady) {
      return (
        <div className="placeholder" style={{ marginTop: 18 }}>
          R isn't installed on this server, so R code can't run here.<br />Export the .qmd and open it in RStudio, or run the same blocks as:
          <span style={{ display: 'flex', gap: 8 }}>
            <button className="btn small" onClick={() => dispatch({ type: 'lang', lang: 'sql' })}>SQL</button>
            <button className="btn small" onClick={() => dispatch({ type: 'lang', lang: 'python' })}>Python</button>
          </span>
        </div>
      );
    }
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
    <>
      <div className="status" data-testid="run-status">
        {run.ok ? `Ran as ${LANG_LABEL[run.target]}${rows ? ` · ${rows}` : ''}${run.plots.length ? ` · ${run.plots.length} plot${run.plots.length > 1 ? 's' : ''}` : ''}`
          : `${LANG_LABEL[run.target]} stopped with a problem`}
        {run.target !== lang && (lang === 'r' && !state.rReady
          ? ` · R can't run on this server, so this is the ${LANG_LABEL[run.target]} result`
          : ' · the language has changed since, press Run again')}
      </div>
      {run.error && (
        <div className="errcard" role="button" tabIndex={0} data-testid="run-error"
          onClick={() => run.error?.block_id && dispatch({ type: 'focus', id: run.error.block_id })}
          onKeyDown={(e) => e.key === 'Enter' && run.error?.block_id && dispatch({ type: 'focus', id: run.error.block_id })}>
          <h3>{run.error.kind === 'NoR' ? 'R is not installed'
            : run.error.kind === 'RawCodeBlocked' ? "Code blocks can't run here"
            : `${run.error.kind}${run.error.line ? ` on line ${run.error.line}` : ''}`}</h3>
          <p>{run.error.message}</p>
          {run.error.detail && run.error.detail !== run.error.message && <code>{run.error.detail}</code>}
          {run.error.block_id && <span className="go">Show me the block →</span>}
        </div>
      )}
      {run.tables.map((t, i) => <ResultTable key={t.name + i} t={t} showName={run.tables.length > 1} />)}
      {run.stdout && <div className="stdout" data-testid="stdout">{run.stdout}</div>}
      {run.plots.length > 0 && (
        <div className="status"><button className="btn tiny" onClick={() => dispatch({ type: 'tab', tab: 'plot' })}>See the plot{run.plots.length > 1 ? 's' : ''} →</button></div>
      )}
    </>
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
