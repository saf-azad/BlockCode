import { python } from '@codemirror/lang-python';
import { sql, SQLite } from '@codemirror/lang-sql';
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language';
import { r as rMode } from '@codemirror/legacy-modes/mode/r';
import { linter, lintGutter, setDiagnostics, type Diagnostic as CmDiagnostic } from '@codemirror/lint';
import { Annotation, Compartment, EditorState, RangeSetBuilder, StateEffect, StateField } from '@codemirror/state';
import { Decoration, EditorView, keymap, lineNumbers, type DecorationSet } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { tags as t } from '@lezer/highlight';
import { useEffect, useMemo, useRef } from 'react';
import { api } from '../api';
import { hasPythonOnly } from '../ir';
import { effectiveLang, useStore } from '../store';
import { LANG_LABEL, LANGS, type Lang } from '../types';

const External = Annotation.define<boolean>();
const setMarks = StateEffect.define<{ hover: number[]; focus: number[] }>();

const marks = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(deco, tr) {
    deco = deco.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setMarks)) continue;
      const b = new RangeSetBuilder<Decoration>();
      const lines = new Map<number, string>();
      for (const n of e.value.hover) lines.set(n, 'hl');
      for (const n of e.value.focus) lines.set(n, 'focusline');
      for (const n of [...lines.keys()].sort((x, y) => x - y)) {
        if (n < 1 || n > tr.state.doc.lines) continue;
        b.add(tr.state.doc.line(n).from, tr.state.doc.line(n).from, Decoration.line({ class: lines.get(n)! }));
      }
      deco = b.finish();
    }
    return deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.operatorKeyword, t.controlKeyword, t.definitionKeyword, t.moduleKeyword], color: 'var(--kw)', fontWeight: '700' },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: 'var(--kw)', fontWeight: '700' },
  { tag: [t.string, t.special(t.string)], color: '#2E6B4F' },
  { tag: [t.number, t.bool, t.null], color: '#8a4b08' },
  { tag: [t.comment, t.meta], color: '#888888', fontStyle: 'italic' },
  { tag: t.heading, fontWeight: '700' },
]);

function language(lang: Lang) {
  if (lang === 'sql') return sql({ dialect: SQLite, upperCaseKeywords: true });
  if (lang === 'python') return python();
  return StreamLanguage.define(rMode);
}

const FILE: Record<Lang, string> = { sql: 'query.sql', python: 'analysis.py', r: 'analysis.qmd' };

export function CodePanel() {
  const { state, dispatch } = useStore();
  const lang = effectiveLang(state);
  const gen = state.generated?.[lang];
  const editing = state.editing && state.editing.lang === lang ? state.editing : null;
  const text = editing ? editing.text : gen?.code ?? '';
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const langSlot = useRef(new Compartment());
  const sqlOff = hasPythonOnly(state.program);

  // block id → lines, from the parse while typing, else from the generated source map
  const linesFor = useMemo(() => {
    const m = new Map<string, number[]>();
    if (editing?.parse?.ok) {
      for (const [id, ls] of Object.entries(editing.parse.spans)) m.set(id, ls);
    } else if (gen && !editing) {
      for (const ln of gen.lines) for (const b of ln.blocks) m.set(b, [...(m.get(b) ?? []), ln.n]);
    }
    return m;
  }, [editing, gen]);
  const blocksAt = useMemo(() => {
    const m = new Map<number, string[]>();
    for (const [id, ls] of linesFor) for (const n of ls) m.set(n, [...(m.get(n) ?? []), id]);
    return m;
  }, [linesFor]);
  const blocksAtRef = useRef(blocksAt);
  blocksAtRef.current = blocksAt;

  // create the editor once
  useEffect(() => {
    if (!host.current) return;
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: text,
        extensions: [
          lineNumbers(),
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          langSlot.current.of(language(lang)),
          syntaxHighlighting(highlight),
          marks,
          lintGutter(),
          linter(null),
          EditorView.lineWrapping,
          EditorView.contentAttributes.of({ 'aria-label': 'Code', 'data-testid': 'code' }),
          EditorView.updateListener.of((u) => {
            if (u.docChanged && !u.transactions.some((tr) => tr.annotation(External))) {
              dispatch({ type: 'edit', text: u.state.doc.toString() });
            }
          }),
          EditorView.domEventHandlers({
            mousemove: (e, v2) => {
              const pos = v2.posAtCoords({ x: e.clientX, y: e.clientY });
              if (pos == null) return;
              const n = v2.state.doc.lineAt(pos).number;
              const ids = blocksAtRef.current.get(n);
              dispatch({ type: 'hover', id: ids ? ids[ids.length - 1] : null });
            },
            mouseleave: () => dispatch({ type: 'hover', id: null }),
          }),
        ],
      }),
    });
    view.current = v;
    return () => v.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // switch language
  useEffect(() => {
    view.current?.dispatch({ effects: langSlot.current.reconfigure(language(lang)) });
  }, [lang]);

  // show generated code (unless the learner is typing)
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const cur = v.state.doc.toString();
    if (cur !== text) {
      v.dispatch({ changes: { from: 0, to: cur.length, insert: text }, annotations: External.of(true) });
    }
  }, [text]);

  // parse what was typed, after a pause
  useEffect(() => {
    if (!editing || editing.parse) return;
    const typed = editing.text;
    const timer = setTimeout(async () => {
      try {
        const res = await api.parse(state.projectName, typed, lang, state.program);
        dispatch({ type: 'parsed', parse: res, text: typed });
        if (res.ok && res.program) dispatch({ type: 'program', program: res.program, fromCode: true });
      } catch (e) {
        dispatch({ type: 'toast', message: (e as Error).message });
      }
    }, 450);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing?.text, editing?.parse]);

  // hover / focus highlights
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const hover = state.hover ? linesFor.get(state.hover) ?? [] : [];
    const focus = state.focus ? linesFor.get(state.focus) ?? [] : [];
    const errLine = !editing && state.run?.error?.line && state.run.target === lang ? [state.run.error.line] : [];
    v.dispatch({ effects: setMarks.of({ hover, focus: [...focus, ...errLine] }) });
    if (focus.length && !editing) {
      const line = v.state.doc.line(Math.min(focus[0], v.state.doc.lines));
      v.dispatch({ effects: EditorView.scrollIntoView(line.from, { y: 'center' }) });
    }
  }, [state.hover, state.focus, linesFor, editing, state.run, lang, text]);

  // squiggles for typos and lines that stay as code
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const diags: CmDiagnostic[] = [];
    const add = (line: number | null, severity: CmDiagnostic['severity'], message: string) => {
      if (!line || line > v.state.doc.lines) return;
      const l = v.state.doc.line(line);
      diags.push({ from: l.from, to: Math.max(l.to, l.from + 1 > v.state.doc.length ? l.to : l.to), severity, message });
    };
    if (editing?.parse) {
      for (const d of editing.parse.diagnostics) add(d.line, d.severity === 'error' ? 'error' : 'info', d.message);
    } else if (!editing && state.run?.error?.line && state.run.target === lang) {
      add(state.run.error.line, 'error', state.run.error.message);
    }
    v.dispatch(setDiagnostics(v.state, diags));
  }, [editing?.parse, state.run, lang, editing]);

  const parse = editing?.parse;
  const bad = parse && !parse.ok;
  const rawLines = parse?.ok ? parse.diagnostics.filter((d) => d.severity === 'info').length : 0;

  return (
    <>
      <div className="codebar">
        <span className="file">{FILE[lang]}</span>
        <div className="toggle" role="tablist" aria-label="Language">
          {LANGS.map((l) => {
            const off = l === 'sql' && sqlOff;
            return (
              <button key={l} role="tab" aria-selected={lang === l} className={lang === l ? 'on' : off ? 'off' : ''}
                title={off ? 'Some blocks have no SQL equivalent' : `Show ${LANG_LABEL[l]}`}
                onClick={() => !off && dispatch({ type: 'lang', lang: l })}>
                {LANG_LABEL[l]}
              </button>
            );
          })}
        </div>
      </div>
      {sqlOff && <div className="notice">SQL is off: some blocks (marked with a dashed outline) have no SQL equivalent. The data blocks still compile to pandas and dplyr.</div>}
      {editing && (
        <div className={`notice edit${bad ? ' bad' : ''}`} role="status">
          <span>
            {!parse && 'Reading your code…'}
            {parse?.ok && (rawLines ? `Blocks updated. ${rawLines} line${rawLines > 1 ? 's' : ''} can't be blocks yet, so they stay as code.` : 'Blocks updated from your code.')}
            {bad && <>Blocks unchanged: {parse!.diagnostics[0]?.message}{parse!.diagnostics[0]?.line ? ` (line ${parse!.diagnostics[0].line})` : ''}</>}
          </span>
          <button className="btn tiny" onClick={() => dispatch({ type: 'tidy' })} title="Rewrite the code from the blocks">Tidy</button>
        </div>
      )}
      <div className="cm-wrap" ref={host} />
    </>
  );
}
