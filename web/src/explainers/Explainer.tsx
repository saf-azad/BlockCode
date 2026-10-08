import { useEffect, useRef } from 'react';
import { effectiveLang, useStore } from '../store';
import type { Block, Lang } from '../types';
import { GEO, poseAt, sceneFor, scenes, shade } from './scenes';

const TITLES: Record<string, string> = {
  join_left: 'Join (keep all rows)', foreach: 'For each', setvar: 'Set var', changevar: 'Change var', raw: 'Code',
  derive: 'New column', if: 'If / else',
};

const CAPTIONS: Record<string, string> = {
  join: 'Rows with the same key in both tables pair up. Rows with no partner drop out.',
  join_left: 'Rows with the same key pair up. Rows from the first table with no partner stay, with an empty partner.',
  print: 'Writes a line to the output for each value it is given.',
  if: 'Checks the test on each pass; the inside blocks only run when it holds.',
  while: 'Keeps running the inside blocks until the test stops holding.',
  setvar: 'Puts a value in a named box so later blocks can use it.',
  changevar: 'Adds to the value already in the box.',
  repeat: 'Runs the inside blocks the number of times you pick.',
};

/** The looping isometric diagram for one block type. */
export function Diagram({ type, fields, lang, width = 136 }: { type: string; fields?: Record<string, any>; lang: Lang; width?: number }) {
  const ref = useRef<SVGSVGElement>(null);
  const key = sceneFor(type, fields);
  const scene = scenes(lang)[key];
  useEffect(() => {
    const svg = ref.current;
    if (!svg || !scene) return;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const t0 = performance.now();
    let raf = 0;
    const { s, w, h, ox, oy } = GEO;
    const tick = (now: number) => {
      const t = reduce ? scene.L * 0.6 : ((now - t0) / 1000) % scene.L;
      const gs = Array.from(svg.children) as SVGGElement[];
      const keyed: [number, SVGGElement][] = [];
      gs.forEach((g) => {
        const i = Number(g.dataset.i);
        const c = scene.cubes[i];
        if (!c) return;
        const st = poseAt(c.kf, t);
        const [gl, tp, lf, rt] = Array.from(g.children) as SVGPolygonElement[];
        g.setAttribute('transform', `translate(${(ox + (st.x - st.y) * w).toFixed(2)},${(oy + (st.x + st.y) * h - st.z * s).toFixed(2)})`);
        g.setAttribute('opacity', st.o.toFixed(3));
        gl.setAttribute('opacity', st.g.toFixed(3));
        tp.setAttribute('fill', shade(st.f, 255, 0.38));
        lf.setAttribute('fill', st.f);
        rt.setAttribute('fill', shade(st.f, 0, 0.22));
        keyed.push([st.x + st.y + st.z * 0.9, g]);
      });
      keyed.sort((p, q) => p[0] - q[0]);
      if (keyed.some(([, g], i) => g !== gs[i])) keyed.forEach(([, g]) => svg.appendChild(g));
      if (!reduce) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [scene]);
  if (!scene) return null;
  const { s, w, h } = GEO;
  const top = `0,0 ${w},${-h} 0,${-2 * h} ${-w},${-h}`;
  const left = `0,0 ${-w},${-h} ${-w},${s - h} 0,${s}`;
  const right = `0,0 ${w},${-h} ${w},${s - h} 0,${s}`;
  const hexagon = `0,${-2 * h} ${w},${-h} ${w},${s - h} 0,${s} ${-w},${s - h} ${-w},${-h}`;
  const face = { stroke: '#111111', strokeWidth: 1.5, strokeLinejoin: 'round' as const };
  return (
    <svg ref={ref} viewBox="0 0 150 120" width={width} height={Math.round(width * 0.8)} data-scene={key} style={{ display: 'block', overflow: 'visible' }} aria-hidden="true">
      {scene.cubes.map((_, i) => (
        <g key={i} data-i={i} opacity={0}>
          <polygon points={hexagon} fill="none" stroke={scene.acc} strokeWidth={6} strokeLinejoin="round" opacity={0} />
          <polygon points={top} {...face} />
          <polygon points={left} {...face} />
          <polygon points={right} {...face} />
        </g>
      ))}
    </svg>
  );
}

export function Explainer({ type, block, placement }: { type: string; block: Block; placement: 'above' | 'below' }) {
  const { state } = useStore();
  const lang = effectiveLang(state);
  const key = sceneFor(type, block.fields);
  const spec = state.specs[type];
  const title = TITLES[key] ?? spec?.labels?.[lang] ?? type;
  const caption = CAPTIONS[key] ?? spec?.caption ?? '';
  if (!scenes(lang)[key]) return null;
  return (
    <div className={`explainer ${placement}`} role="tooltip">
      <div className="art"><Diagram type={type} fields={block.fields} lang={lang} /></div>
      <div className="txt"><b>{title}</b><span>{caption}</span></div>
    </div>
  );
}
