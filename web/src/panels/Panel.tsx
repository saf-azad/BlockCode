import { CodePanel } from '../code/CodePanel';
import { effectiveLang, useStore, type Tab } from '../store';
import { Output } from './Output';
import { Plots } from './Plots';
import { Problems, useProblems } from './Problems';

export function Panel() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);
  const problems = useProblems();
  const errors = problems.some((p) => p.kind === 'error');
  const tab = (id: Tab, label: string, extra?: React.ReactNode, cls = '') => (
    <button role="tab" aria-selected={state.tab === id} className={`tab${state.tab === id ? ' on' : ''}${cls}`}
      onClick={() => dispatch({ type: 'tab', tab: id })}>{label}{extra}</button>
  );
  return (
    <section className="panel" aria-label="Code and results">
      <div className="tabs" role="tablist">
        {tab('code', 'Code')}
        {tab('output', 'Output')}
        {tab('plot', 'Plot', null, lang === 'sql' ? ' off' : '')}
        {tab('problems', 'Problems', <span className={`badge${errors ? ' err' : problems.length ? ' some' : ''}`}>{problems.length}</span>)}
      </div>
      <div className="panel-body" style={{ display: state.tab === 'code' ? 'flex' : 'none' }}><CodePanel /></div>
      {state.tab === 'output' && <div className="panel-body"><Output /></div>}
      {state.tab === 'plot' && <div className="panel-body"><Plots /></div>}
      {state.tab === 'problems' && <div className="panel-body"><Problems /></div>}
    </section>
  );
}
