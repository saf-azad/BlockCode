import { useEffect, useRef, type ReactNode } from 'react';

/** A small dialog in the v4 style. Escape or a click outside closes it. */
export function Modal({ title, children, onClose, actions, wide = false }: {
  title: string; children: ReactNode; onClose: () => void; actions: ReactNode; wide?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    const first = box.current?.querySelector<HTMLElement>('textarea, input, button.primary');
    first?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} ref={box}>
        <h2>{title}</h2>
        <div className="modal-body">{children}</div>
        <div className="modal-actions">{actions}</div>
      </div>
    </div>
  );
}

/** "Are you sure?" with a clear consequence and a named action. */
export function Confirm({ title, children, action, onConfirm, onClose }: {
  title: string; children: ReactNode; action: string; onConfirm: () => void; onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose} actions={(
      <>
        <button className="btn small" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={() => { onConfirm(); onClose(); }}>{action}</button>
      </>
    )}>
      {children}
    </Modal>
  );
}
