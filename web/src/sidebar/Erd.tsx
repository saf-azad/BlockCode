import { useEffect, useState } from 'react';
import { api } from '../api';
import { useStore } from '../store';
import type { Erd } from '../types';

type Notation = 'crow' | 'chen' | 'uml';
const W = 220;
const HEAD = 38;
const ROW = 30;

interface Box { name: string; x: number; y: number; w: number; h: number; hub: boolean }

function layout(erd: Erd): Box[] {
  const manyCount = (n: string) => erd.links.filter((l) => l.many === n).length;
  const order = [...erd.tables].sort((a, b) => manyCount(b.name) - manyCount(a.name));
  const hub = order[0];
  const rest = order.slice(1);
  const row: typeof order = [];
  rest.forEach((t, i) => (i % 2 === 0 ? row.unshift(t) : row.push(t)));
  if (hub) row.splice(Math.floor(row.length / 2), 0, hub); // the most-linked table goes in the middle
  const perRow = 3;
  return row.map((t, i) => {
    const r = Math.floor(i / perRow);
    const c = i % perRow;
    const h = HEAD + t.columns.length * ROW;
    return { name: t.name, x: 40 + c * 300, y: 30 + r * 260 + (t.name === hub?.name ? 0 : 30), w: W, h, hub: t.name === hub?.name && manyCount(t.name) > 0 };
  });
}

export function ErdPanel() {
  const { state, dispatch } = useStore();
  const [erd, setErd] = useState<Erd | null>(null);
  const [notation, setNotation] = useState<Notation>('crow');
  const tables = state.project?.tables;
  useEffect(() => {
    api.erd(tables ?? []).then(setErd).catch(() => setErd(null));
  }, [tables]);
  if (!erd) return null;
  const boxes = layout(erd);
  const box = (n: string) => boxes.find((b) => b.name === n)!;
  const colY = (b: Box, col: string) => {
    const t = erd.tables.find((x) => x.name === b.name)!;
    return b.y + HEAD + t.columns.findIndex((c) => c.name === col) * ROW + ROW / 2;
  };
  const width = Math.max(...boxes.map((b) => b.x + b.w)) + 40;
  const height = Math.max(...boxes.map((b) => b.y + b.h)) + 30;

  const links = erd.links.map((l) => {
    const one = box(l.one);
    const many = box(l.many);
    const leftToRight = one.x < many.x;
    const x1 = leftToRight ? one.x + one.w : one.x;
    const x2 = leftToRight ? many.x : many.x + many.w;
    const y1 = colY(one, l.column);
    const y2 = colY(many, l.column);
    const mid = (x1 + x2) / 2;
    return { l, x1, x2, y1, y2, mid, dir: leftToRight ? 1 : -1 };
  });

  const note = erd.links.length
    ? `Columns with the same name in two tables are treated as links: ${[...new Set(erd.links.map((l) => l.column))].join(' and ')}.`
    : 'No two tables share a column name, so nothing links up yet.';
  const unlinked = erd.unlinked.length && erd.links.length
    ? ` Nothing links ${erd.unlinked.map(([a, b]) => `${a} and ${b}`).join(', ')} directly.` : '';
  const explain: Record<Notation, string> = {
    crow: erd.links.filter((l) => l.kind === '1-*').map((l) => `One row of ${l.one} has many in ${l.many}.`).join(' '),
    uml: 'Multiplicities read 1 on the one side and * on the many side.',
    chen: 'Tables whose rows join two others read as relationships (diamonds) between them.',
  };

  return (
    <div className="erd" role="dialog" aria-label="Quick ERD">
      <div className="bar">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <b>Quick ERD</b>
          <span style={{ fontSize: 13, color: 'var(--muted)' }}>{erd.tables.length} tables, {erd.links.length} link{erd.links.length === 1 ? '' : 's'}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ display: 'flex', gap: 6 }}>
            {([['crow', "Crow's foot"], ['chen', 'Chen'], ['uml', 'UML']] as [Notation, string][]).map(([k, label]) => (
              <button key={k} className={`btn tiny${notation === k ? ' on' : ''}`} onClick={() => setNotation(k)}>{label}</button>
            ))}
          </div>
          <button className="x" style={{ borderRadius: '50%', marginLeft: 0 }} title="Close" onClick={() => dispatch({ type: 'erd', open: false })}>×</button>
        </div>
      </div>
      <div className="canvas">
        {notation === 'chen' ? <Chen erd={erd} /> : (
          <div style={{ position: 'relative', width, height }}>
            <svg width={width} height={height} style={{ position: 'absolute', inset: 0 }} fill="none" stroke="#111111" strokeWidth={2}>
              {links.map(({ l, x1, x2, y1, y2, mid, dir }, i) => (
                <g key={i}>
                  <path d={`M${x1} ${y1} H${mid} V${y2} H${x2}`} />
                  {notation === 'crow' && (
                    <>
                      <path d={`M${x1 + 12 * dir} ${y1 - 10} V${y1 + 10}`} />
                      {l.kind !== '1-1' && <path d={`M${x2 - 14 * dir} ${y2} L${x2} ${y2 - 10} M${x2 - 14 * dir} ${y2} L${x2} ${y2} M${x2 - 14 * dir} ${y2} L${x2} ${y2 + 10}`} />}
                      {l.kind === '1-1' && <path d={`M${x2 - 12 * dir} ${y2 - 10} V${y2 + 10}`} />}
                    </>
                  )}
                  {notation === 'uml' && (
                    <>
                      <text x={x1 + 8 * dir} y={y1 - 8} fill="#111" stroke="none" fontFamily="Space Mono, monospace" fontSize={12} fontWeight={700} textAnchor={dir > 0 ? 'start' : 'end'}>1</text>
                      <text x={x2 - 8 * dir} y={y2 - 8} fill="#111" stroke="none" fontFamily="Space Mono, monospace" fontSize={12} fontWeight={700} textAnchor={dir > 0 ? 'end' : 'start'}>{l.kind === '1-1' ? '1' : '*'}</text>
                    </>
                  )}
                </g>
              ))}
            </svg>
            {boxes.map((b) => {
              const t = erd.tables.find((x) => x.name === b.name)!;
              return (
                <div key={b.name} className="erd-table" style={{ left: b.x, top: b.y, width: b.w, borderRadius: notation === 'uml' ? 4 : '12px 12px 6px 6px' }}>
                  <div className={`h${b.hub ? ' hub' : ''}`} style={{ textAlign: notation === 'uml' ? 'center' : 'left' }}>{t.name}</div>
                  {t.columns.map((c) => (
                    <div className="r" key={c.name}>
                      <span style={{ fontWeight: c.pk || c.fk ? 700 : 600, textDecoration: c.pk ? 'underline' : 'none' }}>
                        {notation === 'crow' && c.pk ? 'PK ' : ''}{notation === 'crow' && c.fk ? 'FK ' : ''}{c.name}
                      </span>
                      <i>{c.type}</i>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="foot"><b>Inferred</b><span>{explain[notation]} {note}{unlinked}</span></div>
    </div>
  );
}

/** Chen notation: entities (rectangles) with attribute ovals; a table that joins two others
 * becomes a relationship diamond with its own attributes. */
function Chen({ erd }: { erd: Erd }) {
  const assoc = erd.tables.filter((t) => erd.links.filter((l) => l.many === t.name).length >= 2);
  const entities = erd.tables.filter((t) => !assoc.includes(t));
  const ex = (i: number) => 820 / Math.max(1, entities.length) * (i + 0.5) + 30;
  const pos = new Map(entities.map((t, i) => [t.name, { x: entities.length === 1 ? 420 : ex(i), y: 190 }]));
  const els: React.ReactNode[] = [];
  const text = (x: number, y: number, s: string, u = false, k = '') => (
    <text key={k || `${x}-${y}-${s}`} x={x} y={y} textAnchor="middle" dominantBaseline="middle" textDecoration={u ? 'underline' : undefined} fill="#111">{s}</text>
  );
  const slot = 820 / Math.max(1, entities.length);
  for (const t of entities) {
    const p = pos.get(t.name)!;
    const gap = Math.min(76, (slot - 40) / Math.max(1, t.columns.length - 1));
    t.columns.forEach((c, i) => {
      const ax = p.x + (i - (t.columns.length - 1) / 2) * gap;
      const ay = 40 + (i % 3) * 30;
      els.push(<path key={`l${t.name}${c.name}`} d={`M${ax} ${ay} L${p.x} ${p.y - 25}`} stroke="#111" strokeWidth={2} />);
      els.push(<ellipse key={`e${t.name}${c.name}`} cx={ax} cy={ay} rx={Math.max(26, c.name.length * 4)} ry={14} fill="#fff" stroke="#111" strokeWidth={2} />);
      els.push(text(ax, ay + 1, c.name, c.pk, `t${t.name}${c.name}`));
    });
    els.push(<rect key={`r${t.name}`} x={p.x - 60} y={p.y - 25} width={120} height={50} fill="var(--c2)" stroke="#111" strokeWidth={2} />);
    els.push(<text key={`n${t.name}`} x={p.x} y={p.y + 1} textAnchor="middle" dominantBaseline="middle" fontFamily="League Spartan, sans-serif" fontWeight={800} fontSize={16} fill="#111">{t.name}</text>);
  }
  for (const a of assoc) {
    const ends = erd.links.filter((l) => l.many === a.name).map((l) => pos.get(l.one)).filter(Boolean) as { x: number; y: number }[];
    const cx = ends.reduce((s, e) => s + e.x, 0) / ends.length;
    const cy = 190;
    ends.forEach((e, i) => {
      els.push(<path key={`a${a.name}${i}`} d={`M${e.x + (e.x < cx ? 60 : -60)} ${e.y} H${cx + (e.x < cx ? -70 : 70)}`} stroke="#111" strokeWidth={2} />);
      els.push(<text key={`m${a.name}${i}`} x={(e.x + cx) / 2} y={cy - 12} textAnchor="middle" fontFamily="Space Mono, monospace" fontWeight={700} fontSize={13} fill="#111">{i === 0 ? 'M' : 'N'}</text>);
    });
    const own = a.columns.filter((c) => !c.fk);
    own.forEach((c, i) => {
      const ax = cx + (i - (own.length - 1) / 2) * 100;
      els.push(<path key={`al${c.name}`} d={`M${ax} 290 L${cx} 230`} stroke="#111" strokeWidth={2} />);
      els.push(<ellipse key={`ae${c.name}`} cx={ax} cy={300} rx={Math.max(30, c.name.length * 4.2)} ry={17} fill="#fff" stroke="#111" strokeWidth={2} />);
      els.push(text(ax, 301, c.name, false, `at${c.name}`));
    });
    els.push(<path key={`d${a.name}`} d={`M${cx} ${cy - 40} L${cx + 70} ${cy} L${cx} ${cy + 40} L${cx - 70} ${cy} Z`} fill="var(--acc)" stroke="#111" strokeWidth={2} />);
    els.push(<text key={`dn${a.name}`} x={cx} y={cy + 1} textAnchor="middle" dominantBaseline="middle" fontFamily="League Spartan, sans-serif" fontWeight={800} fontSize={14} fill="#111">{a.name}</text>);
  }
  return (
    <svg width={880} height={340} viewBox="0 0 880 340" fontFamily="DM Sans, sans-serif" fontSize={13} fontWeight={600}>{els}</svg>
  );
}
