import { find } from '../ir';
import { effectiveLang, useStore } from '../store';
import { LANG_LABEL } from '../types';

export interface Problem {
  kind: 'error' | 'warning' | 'sql' | 'info';
  label: string;
  message: string;
  blockId: string | null;
  where: string;
}

const SEV: Record<Problem['kind'], { label: string; bg: string; fg: string }> = {
  error: { label: 'Error', bg: 'var(--error)', fg: '#fff' },
  warning: { label: 'Check', bg: '#ffffff', fg: 'var(--ink)' },
  sql: { label: 'SQL', bg: 'var(--ink)', fg: 'var(--c1)' },
  info: { label: 'Note', bg: 'var(--c2)', fg: 'var(--ink)' },
};

const NAME: Record<string, string> = {
  from: 'From', join: 'Join', where: 'Where', derive: 'New column', group: 'Group by', having: 'Having', select: 'Select',
  order: 'Order by', limit: 'Limit', setvar: 'Set var', changevar: 'Change var', print: 'Print', foreach: 'For each',
  repeat: 'Repeat', if: 'If / else', while: 'While', plot: 'Plot', raw: 'Code',
};

export function useProblems(): Problem[] {
  const { state } = useStore();
  const lang = effectiveLang(state);
  const out: Problem[] = [];
  const where = (id: string | null, line?: number | null) => {
    const b = id ? find(state.program, id) : null;
    const name = b ? NAME[b.type] ?? b.type : '';
    return [name, line ? `L${line}` : ''].filter(Boolean).join(' · ');
  };
  const run = state.run;
  const said = new Set<string>(); // the run's own error, so a check saying the same isn't listed twice
  if (run?.error && run.target === lang) {
    out.push({ kind: 'error', label: 'Error', message: run.error.message, blockId: run.error.block_id, where: where(run.error.block_id, run.error.line) });
    said.add(`${run.error.message}|${run.error.block_id}`);
  }
  if (state.editing?.parse && !state.editing.parse.ok) {
    for (const d of state.editing.parse.diagnostics) out.push({ kind: 'error', label: 'Error', message: d.message, blockId: null, where: d.line ? `L${d.line}` : '' });
  }
  const seen = new Set<string>();
  // the SQL problems explain why SQL is off, even while another language is shown
  const sqlDiags = (state.generated?.sql?.diagnostics ?? []).filter((d) => d.severity === 'sql');
  for (const d of [...(state.generated?.[lang]?.diagnostics ?? []), ...(lang === 'sql' ? [] : sqlDiags)]) {
    if (d.severity === 'info' || said.has(`${d.message}|${d.block_id}`)) continue;
    const key = `${d.severity}|${d.message}|${d.block_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ kind: d.severity, label: SEV[d.severity].label, message: d.message, blockId: d.block_id, where: where(d.block_id) });
  }
  return out;
}

export function Problems() {
  const { state, dispatch } = useStore();
  const problems = useProblems();
  const lang = effectiveLang(state);
  if (!problems.length) {
    return <div className="problems"><div style={{ padding: '10px 2px', fontSize: 15, color: 'var(--muted)' }}>
      No problems. This program {state.generated?.sql?.ok === false ? `runs as ${LANG_LABEL[lang]}` : 'exports to SQL, Python and R'}.
    </div></div>;
  }
  return (
    <div className="problems" data-testid="problems">
      {problems.map((p, i) => (
        <button key={i} className="problem" onClick={() => {
          if (p.blockId) {
            dispatch({ type: 'focus', id: p.blockId });
            document.getElementById(`blk-${p.blockId}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
          }
        }}>
          <span className="sev" style={{ background: SEV[p.kind].bg, color: SEV[p.kind].fg, border: p.kind === 'warning' ? '1.5px solid var(--ink)' : undefined }}>{p.label}</span>
          <span className="msg">{p.message}</span>
          <span className="where">{p.where}</span>
        </button>
      ))}
    </div>
  );
}
