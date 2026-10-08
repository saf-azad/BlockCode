import { setField, walk } from '../ir';
import { effectiveLang, useEdit, useStore } from '../store';
import { makeBlock } from '../stack/make';
import { insertBlock } from '../ir';
import { useRun } from './run';

const CHARTS = [['bar', 'Bar'], ['line', 'Line'], ['scatter', 'Scatter'], ['hist', 'Histogram']];

export function Plots() {
  const { state, dispatch } = useStore();
  const edit = useEdit();
  const doRun = useRun();
  const lang = effectiveLang(state);
  const plots = [...walk(state.program.blocks)].filter((b) => b.type === 'plot');
  const images = state.run && state.run.target === lang ? state.run.plots : [];
  const addPlot = () => {
    const b = makeBlock('plot', state.program, state.project?.tables ?? []);
    dispatch({ type: 'program', program: insertBlock(state.program, b, null, '', state.program.blocks.length) });
  };
  const sql = lang === 'sql';
  return (
    <div className="plots">
      {sql && (
        <div className="detached-note">
          <span>SQL has no plotting, so plot blocks are detached and paused. Switch to Python or R to draw them.</span>
          <button className="btn tiny" onClick={() => dispatch({ type: 'lang', lang: 'python' })}>Python</button>
          <button className="btn tiny" onClick={() => dispatch({ type: 'lang', lang: 'r' })}>R</button>
        </div>
      )}
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
              <button key={k} className={`btn tiny${p.fields.chart === k ? ' on' : ''}`} onClick={() => edit((prog) => setField(prog, p.id, 'chart', k))}>{label}</button>
            ))}
          </div>
          {images[i] && !sql ? (
            <img src={`data:image/png;base64,${images[i]}`} alt={`${p.fields.chart} chart of ${p.fields.y ?? p.fields.x} by ${p.fields.x}`} />
          ) : (
            <div className="placeholder" style={{ margin: 0, minHeight: 120 }}>
              {sql ? 'Paused in SQL' : 'Press Run to draw it'}
              {!sql && <button className="btn tiny" onClick={doRun}>Run</button>}
            </div>
          )}
        </div>
      ))}
      {plots.length > 0 && !sql && <button className="btn small" style={{ alignSelf: 'flex-start' }} onClick={addPlot}>+ Add another plot</button>}
    </div>
  );
}
