import { createContext, useContext, type ReactNode } from 'react';
import type { Col } from '../ir';
import type { Lang } from '../types';

// ---- what the current block can see ---------------------------------------------------------

export interface Scope {
  lang: Lang;
  columns: Col[]; // columns in a data step
  imperative: boolean; // inside Python/R statements (variables, not columns)
  vars: string[];
  rowFields: { name: string; columns: Col[] }[]; // loop variables and the columns of their rows
  stacks: string[]; // names of data stacks (for For each / Plot)
  tables: string[];
}

export const ScopeCtx = createContext<Scope>({
  lang: 'sql', columns: [], imperative: false, vars: [], rowFields: [], stacks: [], tables: [],
});
export const useScope = () => useContext(ScopeCtx);

export function ScopeProvider({ value, children }: { value: Partial<Scope>; children: ReactNode }) {
  const parent = useScope();
  return <ScopeCtx.Provider value={{ ...parent, ...value }}>{children}</ScopeCtx.Provider>;
}

// ---- language words ------------------------------------------------------------------------------

export const WORDS: Record<Lang, Record<string, string>> = {
  sql: {
    using: 'USING', as: 'AS', rows: 'rows', of: 'of', and: 'AND', or: 'OR', not: 'NOT', empty: 'IS NULL',
    in: 'IN', contains: 'LIKE %…%', starts: 'LIKE …%', ends: 'LIKE %…', eq: '=', join: 'JOIN', left: 'LEFT JOIN',
    avg: 'AVG', count: 'COUNT', sum: 'SUM', min: 'MIN', max: 'MAX',
  },
  python: {
    using: 'on', as: '=', rows: '', of: 'of', and: '&', or: '|', not: '~', empty: '.isna()', in: '.isin', contains: 'contains',
    starts: 'startswith', ends: 'endswith', eq: '==', join: 'merge', left: 'merge (left)',
    avg: 'mean', count: 'size', sum: 'sum', min: 'min', max: 'max',
  },
  r: {
    using: 'by', as: '=', rows: '', of: 'of', and: '&', or: '|', not: '!', empty: 'is.na', in: '%in%', contains: 'str_detect',
    starts: 'str_starts', ends: 'str_ends', eq: '==', join: 'inner_join', left: 'left_join',
    avg: 'mean', count: 'n', sum: 'sum', min: 'min', max: 'max',
  },
};

export function useWords() {
  return WORDS[useScope().lang];
}

// ---- pills -----------------------------------------------------------------------------------------

interface PickProps {
  value: string | null | undefined;
  options: (string | { value: string; label: string })[];
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  title?: string;
  label?: string;
}

/** A dropdown that looks like the design's "dept ▾" pill. */
export function Pick({ value, options, onChange, placeholder = 'pick', className = 'f', title, label }: PickProps) {
  const opts = options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o));
  if (value && !opts.some((o) => o.value === value)) opts.unshift({ value, label: value });
  const shown = label ?? opts.find((o) => o.value === value)?.label ?? placeholder;
  return (
    <label className={className} title={title} onPointerDown={(e) => e.stopPropagation()}>
      {shown} ▾
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value)} aria-label={title ?? placeholder}>
        {!value && <option value="">{placeholder}</option>}
        {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function TextIn({ value, onChange, placeholder = '', className = 'f', title, mono = true }: {
  value: string; onChange: (v: string) => void; placeholder?: string; className?: string; title?: string; mono?: boolean;
}) {
  return (
    <span className={className} title={title} style={mono ? undefined : { fontFamily: 'var(--body)' }}>
      <input
        value={value}
        placeholder={placeholder}
        size={Math.max(2, (value || placeholder).length)}
        onChange={(e) => onChange(e.target.value)}
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        aria-label={title ?? placeholder}
      />
    </span>
  );
}

export function NumIn({ value, onChange, title }: { value: number; onChange: (v: number) => void; title?: string }) {
  return (
    <span className="f" title={title}>
      <input
        type="text"
        inputMode="numeric"
        value={String(value ?? '')}
        size={Math.max(2, String(value ?? '').length)}
        onChange={(e) => {
          const n = parseInt(e.target.value.replace(/[^0-9]/g, '') || '0', 10);
          onChange(n);
        }}
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        aria-label={title}
      />
    </span>
  );
}

export function ColumnPick({ value, onChange, title, columns }: {
  value: string | null; onChange: (v: string) => void; title?: string; columns?: Col[];
}) {
  const scope = useScope();
  const cols = columns ?? scope.columns;
  return <Pick value={value} options={cols.map((c) => c.name)} onChange={onChange} placeholder="column" title={title ?? 'Column'} />;
}

/** Column chips with × and a "+" picker (Group by keys, Select columns). */
export function ColumnChips({ value, onChange, title }: { value: string[]; onChange: (v: string[]) => void; title: string }) {
  const { columns } = useScope();
  const rest = columns.map((c) => c.name).filter((c) => !value.includes(c));
  return (
    <span className="chips">
      {value.map((c, i) => (
        <span className="f" key={c + i}>
          {c}
          <button className="chip-x" title={`Remove ${c}`} onPointerDown={(e) => e.stopPropagation()}
            onClick={() => onChange(value.filter((_, j) => j !== i))}>×</button>
        </span>
      ))}
      {rest.length > 0 && (
        <label className="add" title={title} onPointerDown={(e) => e.stopPropagation()}>
          +
          <select value="" onChange={(e) => e.target.value && onChange([...value, e.target.value])} aria-label={title}>
            <option value="">{title}</option>
            {rest.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      )}
    </span>
  );
}
