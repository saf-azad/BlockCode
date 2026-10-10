import { useState } from 'react';
import { Modal } from '../Modal';
import { useStore } from '../store';
import { useUpload } from './upload';

const clean = (s: string) => s.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');

/** Paste cells from a spreadsheet (tab separated) or CSV text to make a table. */
export function PasteData({ onClose }: { onClose: () => void }) {
  const { state } = useStore();
  const upload = useUpload();
  const taken = new Set((state.project?.tables ?? []).map((t) => t.name));
  const [name, setName] = useState(() => {
    let n = 'pasted_data';
    for (let i = 2; taken.has(n); i++) n = `pasted_data_${i}`;
    return n;
  });
  const [text, setText] = useState('');
  const table = clean(name) || 'pasted_data';
  const lines = text.trim() ? text.trim().split(/\r?\n/).length : 0;

  const add = () => {
    if (!text.trim()) return;
    onClose();
    upload(new File([text], `${table}.csv`, { type: 'text/csv' }));
  };

  return (
    <Modal title="Paste data" wide onClose={onClose} actions={(
      <>
        <span className="modal-note">{lines ? `${lines - 1} row${lines === 2 ? '' : 's'} + a header` : ''}</span>
        <button className="btn small" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={!lines} onClick={add}>Add table</button>
      </>
    )}>
      <p>Copy cells from Excel or Google Sheets (with the header row), or CSV text, and paste them below.</p>
      <label className="field">
        <span>Table name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} spellCheck={false} aria-label="Table name" />
      </label>
      {taken.has(table) && <div className="modal-warn">This replaces the table {table}.</div>}
      <textarea className="paste" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
        aria-label="Data to paste" placeholder={'name,age,city\nAna,31,Paris\nBo,25,Lyon'} />
    </Modal>
  );
}
