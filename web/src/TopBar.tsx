import { useState } from 'react';
import { api } from './api';
import { clearWorkspace } from './local';
import { Confirm } from './Modal';
import { useRun } from './panels/run';
import { effectiveLang, storedTables, UNTITLED, useStore } from './store';
import { LANG_LABEL } from './types';

const EXT = { sql: '.sql', python: '.py', r: '.qmd' };

export function TopBar() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);
  const run = useRun();
  const [confirmNew, setConfirmNew] = useState(false);
  const [exporting, setExporting] = useState(false);
  const ready = !!state.project;
  const title = state.project?.title ?? '';
  const empty = !state.program.blocks.length;
  const nothing = empty && !(state.project?.tables.length);
  const rBlocked = lang === 'r' && !state.rReady;

  const doExport = async () => {
    setExporting(true);
    try {
      const blob = await api.export(state.program, lang, title || UNTITLED, storedTables(state));
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const stem = (title || UNTITLED).replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || 'analysis';
      a.href = url;
      a.download = `${stem}-${lang}.zip`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      dispatch({ type: 'toast', message: `Downloaded the ${EXT[lang]} file with its data, ready to run on its own.` });
    } catch (e) {
      dispatch({ type: 'toast', message: (e as Error).message });
    } finally {
      setExporting(false);
    }
  };

  const status = !ready ? '' : !state.canSave ? 'Not saved: this browser blocks storage'
    : state.saved === 'saved' ? 'Saved in this browser' : state.saved === 'saving' ? 'Saving…' : 'Edited';

  return (
    <div className="topbar">
      <div className="left">
        <span className="logo" aria-hidden="true"><i /><i /></span>
        {ready ? (
          <input className="title-input" value={title} placeholder={UNTITLED} maxLength={80} spellCheck={false}
            aria-label="Name of this analysis" size={Math.max(12, Math.min(40, (title || UNTITLED).length + 1))}
            onChange={(e) => dispatch({ type: 'title', title: e.target.value })} />
        ) : <span className="title">BlockCode</span>}
        <span className="status" data-testid="saved" title={state.canSave ? 'Your tables and blocks stay on this device. Nothing is kept on the server.' : 'Private windows and some settings stop sites from storing data.'}>{status}</span>
        <button className="btn tiny" disabled={!state.history.length} onClick={() => dispatch({ type: 'undo' })} title="Undo (Ctrl+Z)">Undo</button>
        <button className="btn tiny" disabled={!state.future.length} onClick={() => dispatch({ type: 'redo' })} title="Redo (Ctrl+Shift+Z)">Redo</button>
      </div>
      <div className="right">
        <button className="btn small" onClick={() => setConfirmNew(true)} disabled={!ready || nothing} title="Start again with an empty workspace">New</button>
        <button className="btn primary" onClick={run} disabled={!ready || state.running || empty || rBlocked} data-testid="run"
          title={empty ? 'Add some blocks first' : rBlocked ? "R isn't installed on this server. Export the .qmd to run it in RStudio." : `Run the ${LANG_LABEL[lang]} code`}>
          <svg width="11" height="11" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1l7 4-7 4z" fill="currentColor" /></svg>
          {state.running ? 'Running…' : `Run ${LANG_LABEL[lang]}`}
        </button>
        <button className="btn" onClick={doExport} disabled={!ready || empty || exporting} data-testid="export"
          title={empty ? 'Add some blocks first' : `Download the ${LANG_LABEL[lang]} code with its data`}>
          {exporting ? 'Exporting…' : `Export ${EXT[lang]}`}
        </button>
      </div>
      {confirmNew && (
        <Confirm title="Start something new?" action="Clear everything" onClose={() => setConfirmNew(false)}
          // wait until the browser has really forgotten the work, or a quick reload could bring it back
          onConfirm={async () => { await clearWorkspace(); dispatch({ type: 'reset' }); }}>
          <p>This removes your blocks and tables from this browser. Export first if you want to keep the code.</p>
        </Confirm>
      )}
    </div>
  );
}
