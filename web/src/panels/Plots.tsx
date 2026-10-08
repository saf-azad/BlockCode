import { insertBlock, resultColumns, setField, walk } from '../ir';
import { makeBlock, plotFields } from '../stack/make';
import { effectiveLang, runIsStale, useEdit, useStore } from '../store';
import { ErrorCard, RunStatus } from './Output';
import { useRun } from './run';

const CHARTS = [['bar', 'Bar'], ['line', 'Line'], ['scatter', 'Scatter'], ['hist', 'Histogram']];

export function Plots() {
  const { state, dispatch } = useStore();
  const edit = useEdit();
  const doRun = useRun();
  const lang = effectiveLang(state);
  const tables = state.project?.tables ?? [];
  const plots = [...walk(state.program.blocks)].filter((b) => b.type === 'plot');
  const run = state.run && state.run.target === lang ? state.run : null;
  const images = run?.plots ?? [];
  // a plot inside a loop draws once per pass, so pictures and blocks only pair up one to one
  // when the counts agree
  const paired = images.length === plots.length;
  const addPlot = () => {
    const b = makeBlock('plot', state.program, tables);
    dispatch({ type: 'program', program: insertBlock(state.program, b, null, '', state.program.blocks.length) });
  };
  const sql = lang === 'sql';
  const waiting = sql ? 'Paused in SQL' : state.running ? 'Drawing…' : run?.error ? 'Not drawn: see the problem above' : 'Press Run to draw it';
  return (
    <div className={`plots${runIsStale(state) || state.running ? ' stale' : ''}`}>
      {sql && (
        <div className="detached-note">
          <span>SQL has no plotting, so plot blocks are detached and paused. Switch to Python or R to draw them.</span>
          <button className="btn tiny" onClick={() => dispatch({ type: 'lang', lang: 'python' })}>Python</button>
          <button className="btn tiny" onClick={() => dispatch({ type: 'lang', lang: 'r' })}>R</button>
        </div>
      )}
      {!sql && <RunStatus />}
      {!sql && run && <ErrorCard />}
      {!plots.length && (
        <div className="placeholder" style={{ margin: 0 }}>
          No plot blocks yet
          <button className="btn small" onClick={addPlot}>+ Add a plot</button>
        </div>
      )}
      {plots.map((p, i) => (
        <div className="plotcard" key={p.id}>
          <div className="bar">
            <b>Figure {i + 1}</b>
            {CHARTS.map(([k, label]) => (
              <button key={k} className={`btn tiny${p.fields.chart === k ? ' on' : ''}`}
                onClick={() => edit((prog) => {
                  const cols = resultColumns(prog, p.fields.data ?? 'out', tables);
                  let out = prog;
                  for (const [f, v] of Object.entries(plotFields({ ...p.fields, chart: k }, cols))) out = setField(out, p.id, f, v);
                  return out;
                })}>{label}</button>
            ))}
          </div>
          {paired && images[i] && !sql ? (
            <img src={`data:image/png;base64,${images[i]}`} alt={`${p.fields.chart} chart of ${p.fields.y ?? p.fields.x} by ${p.fields.x}`} data-testid="plot-image" />
          ) : !paired && images.length && !sql ? null : (
            <div className="placeholder" style={{ margin: 0, minHeight: 120 }}>
              {waiting}
              {!sql && !state.running && !run?.error && <button className="btn tiny" onClick={doRun}>Run</button>}
            </div>
          )}
        </div>
      ))}
      {!paired && !sql && images.map((png, i) => (
        <div className="plotcard" key={`img${i}`}>
          <div className="bar"><b>Picture {i + 1}</b></div>
          <img src={`data:image/png;base64,${png}`} alt={`Plot ${i + 1}`} data-testid="plot-image" />
        </div>
      ))}
      {plots.length > 0 && !sql && <button className="btn small" style={{ alignSelf: 'flex-start' }} onClick={addPlot}>+ Add another plot</button>}
    </div>
  );
}
