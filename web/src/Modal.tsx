import { useEffect, useRef, type ReactNode } from 'react';

/** A small dialog in the v4 style. Escape or a click outside closes it. */
export function Modal({ title, children, onClose, actions, wide = false }: {
  title: string; children: ReactNode; onClose: () => void; actions: ReactNode; wide?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const focusable = () => Array.from(
      box.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])') ?? []);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        close.current();
      } else if (e.key === 'Tab') {
        // keep focus inside the dialog
        const items = focusable();
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        if (e.shiftKey && (active === first || !box.current?.contains(active))) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    // capture so Escape closes the dialog before the app's global key handler runs
    window.addEventListener('keydown', onKey, true);
    (box.current?.querySelector<HTMLElement>('textarea, input, button.primary')
      ?? box.current)?.focus();
    return () => {
      window.removeEventListener('keydown', onKey, true);
      prev?.focus?.();
    };
  }, []);
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
