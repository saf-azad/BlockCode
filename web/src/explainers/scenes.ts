// Isometric "what this block does to the rows" animations. Each cube is one row.
// Ported from the v4 design (src, where, group, having, order, limit, plot, loop) with a new,
// key-matching Join and new scenes for every other block. The numbers come from stories.json,
// which tests/test_explainers.py also runs through the engine.
import stories from './stories.json';
import { PAL, THEMES } from '../theme';
import type { Lang } from '../types';

export interface Pose { x: number; y: number; z: number; o: number; g: number; f: string }
export type Keyframe = [number, Pose];
export interface Cube { kf: Keyframe[]; tag?: string }
export interface Scene { L: number; cubes: Cube[]; acc: string }

export const GEO = { s: 13, w: 11.26, h: 6.5, ox: 75, oy: 66 };

const R = (k: number) => [...Array(k).keys()];

function cube(f: string, kf: [number, Partial<Pose>][], tag?: string): Cube {
  let p: Pose = { x: 0, y: 0, z: 0, o: 1, g: 0, f };
  return { tag, kf: kf.map(([t, d]) => { p = { ...p, ...d }; return [t, p] as Keyframe; }) };
}

/** A cube that fades in at its start pose, then follows ``mids``. */
function C(f: string, st: Partial<Pose>, mids: [number, Partial<Pose>][] = [], tag?: string): Cube {
  return cube(f, [[0, { ...st, o: 0 }], [0.25, { o: st.o ?? 1 }], ...mids], tag);
}

const g3 = (i: number) => ({ x: (i % 3) - 1, y: Math.floor(i / 3) - 1 });
const cache: Partial<Record<Lang, Record<string, Scene>>> = {};

export function scenes(lang: Lang): Record<string, Scene> {
  const hit = cache[lang];
  if (hit) return hit;
  const T = THEMES[lang];
  const P = PAL[lang];
  const n = T.c2;
  const a = T.acc;
  const A = P.from.bg;
  const B = P.group.bg;
  const Cc = P.limit.bg;
  const HOLLOW = '#FFFFFF';
  const xs4 = [-1.8, -0.6, 0.6, 1.8];
  const sc: Record<string, Omit<Scene, 'acc'>> = {};

  sc.from = { L: 3.6, cubes: R(9).map((i) => C(n, { ...g3(i), z: -4, o: 0 }, [[0.3 + i * 0.12, {}], [0.8 + i * 0.12, { z: 0, o: 1 }]])) };

  // Join: key colours show which rows match. Matching pairs slide together; unmatched rows drop
  // out (inner) or keep a hollow, empty partner (left).
  const keyColour: Record<string, string> = { A, B: a, C: Cc, D: B };
  const join = (left: boolean): Omit<Scene, 'acc'> => {
    const st = left ? stories.join_left : stories.join_inner;
    const rightKeys = st.right;
    const cubes: Cube[] = [];
    let row = -1;
    const finalRow: Record<string, number> = {};
    for (const k of st.left) if (rightKeys.includes(k)) finalRow[k] = row++;
    if (left) for (const k of st.left) if (!rightKeys.includes(k)) finalRow[k] = row++;
    st.left.forEach((k, i) => {
      const y = i - 1;
      const kept = k in finalRow;
      cubes.push(C(keyColour[k], { x: -2.6, y }, kept
        ? [[0.7, {}], [1.5, { x: -0.5, y: finalRow[k] }], [1.7, { g: 1 }], [2.5, { g: 0 }]]
        : [[1.2, {}], [1.9, { z: -4, o: 0 }]], `L${k}`));
    });
    rightKeys.forEach((k, i) => {
      const y = i - 1;
      const kept = st.left.includes(k);
      cubes.push(C(keyColour[k], { x: 2.6, y }, kept
        ? [[0.7, {}], [1.5, { x: 0.5, y: finalRow[k] }], [1.7, { g: 1 }], [2.5, { g: 0 }]]
        : [[1.2, {}], [1.9, { z: -4, o: 0 }]], `R${k}`));
    });
    if (left) {
      for (const k of st.left) {
        if (rightKeys.includes(k)) continue;
        cubes.push(cube(HOLLOW, [[0, { x: 2.6, y: finalRow[k], o: 0 }], [1.5, { o: 0 }], [2.1, { x: 0.5, o: 0.9 }], [2.3, { g: 1 }], [2.9, { g: 0 }]], `E${k}`));
      }
    }
    return { L: 3.8, cubes };
  };
  sc.join = join(false);
  sc.join_left = join(true);

  const sel = stories.where.kept;
  sc.where = {
    L: 3.8,
    cubes: R(stories.where.rows).map((i) => C(n, g3(i), sel.includes(i)
      ? [[0.7, {}], [1.1, { f: a, g: 1 }], [2.6, {}], [3.0, { g: 0 }]]
      : [[1.6, {}], [2.3, { z: -4, o: 0 }]], sel.includes(i) ? 'kept' : 'dropped')),
  };

  // New column: every row grows a new cube beside it.
  sc.derive = {
    L: 3.6,
    cubes: [
      ...R(stories.derive.rows).map((i) => C(n, { x: -0.5, y: i - 1 })),
      ...R(stories.derive.rows).map((i) => cube(a, [[0, { x: -0.5, y: i - 1, o: 0 }], [0.6 + i * 0.35, { o: 0 }], [1.1 + i * 0.35, { x: 0.6, o: 1, g: 1 }], [2.4, { g: 0 }]], 'new')),
    ],
  };

  const colours = stories.group.keys.map((k) => ({ A, B, C: Cc } as Record<string, string>)[k]);
  const colX: Record<string, number> = { [A]: -1, [B]: 0, [Cc]: 1 };
  const seen: Record<string, number> = {};
  sc.group = {
    L: 4.4,
    cubes: colours.map((f, i) => {
      const slot = (seen[f] = (seen[f] ?? -1) + 1);
      const to = { x: colX[f], y: slot - 1 };
      return C(f, g3(i), [[0.7, {}], [1.5, to], [2.1, {}], ...(slot === 0
        ? [[2.7, { g: 1 }], [3.5, { g: 0 }]] as [number, Partial<Pose>][]
        : [[2.7, { y: -1, o: 0 }]] as [number, Partial<Pose>][])], slot === 0 ? 'group' : 'merged');
    }),
  };

  sc.having = {
    L: 3.6,
    cubes: stories.having.piles.flatMap((hgt, p) => R(hgt).map((k) => C(n, { x: (p - 1) * 1.5, y: 0, z: k },
      hgt < stories.having.at_least
        ? [[0.8, {}], [1.1, { f: a, g: 1 }], [1.7, {}], [2.3, { z: -4, o: 0 }]]
        : [], hgt < stories.having.at_least ? 'dropped' : 'kept'))),
  };

  // Select: rows are several cubes wide; columns not picked fall away, the rest close up.
  const keep = stories.select.keep;
  sc.select = {
    L: 3.6,
    cubes: R(stories.select.rows).flatMap((r) => R(stories.select.columns).map((c) => C(n, { x: c - 1, y: r - 0.5 },
      keep.includes(c)
        ? [[0.9, {}], [1.2, { f: a, g: 1 }], [1.9, { x: keep.indexOf(c) - 0.5 }], [2.6, { g: 0 }]]
        : [[0.9, {}], [1.6, { z: -4, o: 0 }]], keep.includes(c) ? 'kept' : 'dropped'))),
  };

  const H = stories.order.heights;
  const rank = [...H.keys()].sort((p, q) => H[q] - H[p]);
  const tgt = H.map((_, j) => rank.indexOf(j));
  sc.order = {
    L: 3.8,
    cubes: H.flatMap((hgt, j) => R(hgt).map((k) => C(n, { x: xs4[j], y: 0, z: k }, [[0.8, {}], [1.8, { x: xs4[tgt[j]] }], [2.0, { g: 1 }], [2.7, { g: 0 }]]))),
  };

  sc.limit = {
    L: 3.8,
    cubes: R(stories.limit.rows).map((i) => C(n, { x: i - 3, y: 0 }, i < stories.limit.n
      ? [[0.7, {}], [1.1, { f: a, g: 1 }], [2.5, {}], [2.9, { g: 0 }]]
      : [[1.5, {}], [2.2, { z: -4, o: 0 }]], i < stories.limit.n ? 'kept' : 'dropped')),
  };

  sc.plot = {
    L: 3.8,
    cubes: [3, 4, 2, 1].flatMap((hgt, j) => R(hgt).map((k) => (k === 0
      ? C(a, { x: xs4[j], y: 0 })
      : C(a, { x: xs4[j], y: 0, o: 0 }, [[0.5 + k * 0.25, {}], [1.0 + k * 0.25, { z: k, o: 1 }]])))),
  };

  // For each / Print: a marker steps along the rows; each lights up in turn.
  sc.foreach = {
    L: 4.0,
    cubes: R(4).map((i) => C(n, { x: i - 1.5, y: 0 }, [[0.6 + i * 0.7, {}], [0.8 + i * 0.7, { f: a, g: 1 }], [1.3 + i * 0.7, { f: n, g: 0 }]]))
      .concat([C('#111111', { x: -1.5, y: 0, z: 1.7 }, R(3).flatMap((i) => [[0.9 + i * 0.7, {}], [1.3 + i * 0.7, { x: i - 0.5 }]] as [number, Partial<Pose>][]))]),
  };
  sc.print = {
    L: 4.0,
    cubes: R(4).map((i) => C(n, { x: i - 1.5, y: 0 }, [[0.6 + i * 0.7, {}], [0.8 + i * 0.7, { f: a, g: 1 }], [1.3 + i * 0.7, { f: n, g: 0 }]]))
      .concat(R(4).map((i) => cube(a, [[0, { x: i - 1.5, y: 1.6, z: 0, o: 0 }], [0.8 + i * 0.7, { o: 0 }], [1.2 + i * 0.7, { o: 1 }]], 'printed'))),
  };

  // Repeat: the same step is stamped out n times.
  sc.repeat = {
    L: 3.8,
    cubes: R(stories.repeat.times).map((i) => cube(a, [[0, { x: -1.5, y: 0, z: 2, o: 0 }], [0.4 + i * 0.8, { o: 0 }], [0.6 + i * 0.8, { o: 1 }], [1.1 + i * 0.8, { x: i - 0.5, z: 0, g: 1 }], [1.6 + i * 0.8, { g: 0 }]], 'stamp'))
      .concat([C('#111111', { x: -1.5, y: 0, z: 2 })]),
  };

  // If / else: a test is checked on each row; only some rows light up.
  sc.if = {
    L: 3.8,
    cubes: R(4).map((i) => C(n, { x: i - 1.5, y: 0 }, i % 2 === 0
      ? [[0.6 + i * 0.6, {}], [0.9 + i * 0.6, { f: a, g: 1, z: 0.6 }], [3.0, { g: 0 }]]
      : [[0.6 + i * 0.6, {}], [0.9 + i * 0.6, { z: -0.3 }]], i % 2 === 0 ? 'then' : 'else')),
  };

  // While: keeps adding until the test fails.
  const tall = stories.while.until - stories.while.start;
  sc.while = {
    L: 3.8,
    cubes: [C(n, { x: 0, y: 0, z: 0 }), ...R(tall).map((k) => cube(a, [[0, { x: 0, y: 0, z: k + 3, o: 0 }], [0.5 + k * 0.6, { o: 0 }], [0.7 + k * 0.6, { o: 1 }], [1.1 + k * 0.6, { z: k + 1, g: 1 }], [1.5 + k * 0.6, { g: 0 }]]))],
  };

  // Set / change a variable: a value drops into its box (change adds one on top).
  sc.setvar = { L: 3.0, cubes: [C(a, { x: 0, y: 0, z: 4, o: 0 }, [[0.4, {}], [1.1, { z: 0, o: 1, g: 1 }], [2.0, { g: 0 }]], 'value')] };
  sc.changevar = { L: 3.2, cubes: [C(n, { x: 0, y: 0, z: 0 }), C(a, { x: 0, y: 0, z: 4, o: 0 }, [[0.6, {}], [1.3, { z: 1, o: 1, g: 1 }], [2.2, { g: 0 }]])] };

  // Raw code: the rows go in and come out as written (BlockCode can't show what it does).
  sc.raw = { L: 3.4, cubes: R(3).map((i) => C('#DDDDDD', { x: -1.8, y: i - 1 }, [[0.6, {}], [1.6, { x: 1.8 }], [2.0, { f: n }]])) };

  const out: Record<string, Scene> = {};
  for (const [k, s] of Object.entries(sc)) {
    // every cube fades out at the end so the loop restarts cleanly
    for (const c of s.cubes) {
      const last = c.kf[c.kf.length - 1];
      if (last[0] < s.L - 0.45) c.kf.push([s.L - 0.45, last[1]], [s.L - 0.05, { ...last[1], o: 0 }]);
    }
    out[k] = { ...s, acc: a };
  }
  cache[lang] = out;
  return out;
}

const hex = (c: string) => {
  const v = parseInt(c.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
};
export const shade = (c: string, to: number, u: number) => `rgb(${hex(c).map((v) => Math.round(v + (to - v) * u)).join(',')})`;
const lerpC = (p: string, q: string, u: number) => {
  const A = hex(p);
  const B = hex(q);
  return '#' + A.map((v, i) => Math.round(v + (B[i] - v) * u).toString(16).padStart(2, '0')).join('');
};

/** Pose of a cube at time ``t`` (eased between keyframes). */
export function poseAt(kf: Keyframe[], t: number): Pose {
  if (t <= kf[0][0]) return kf[0][1];
  for (let i = 1; i < kf.length; i++) {
    if (t <= kf[i][0]) {
      const [t0, p] = kf[i - 1];
      const [t1, q] = kf[i];
      const r = (t - t0) / (t1 - t0 || 1);
      const u = r < 0.5 ? 4 * r * r * r : 1 - Math.pow(-2 * r + 2, 3) / 2;
      return {
        x: p.x + (q.x - p.x) * u, y: p.y + (q.y - p.y) * u, z: p.z + (q.z - p.z) * u,
        o: p.o + (q.o - p.o) * u, g: p.g + (q.g - p.g) * u, f: p.f === q.f ? p.f : lerpC(p.f, q.f, u),
      };
    }
  }
  return kf[kf.length - 1][1];
}

/** Which scene a block shows (Join picks inner or left by its setting). */
export function sceneFor(type: string, fields: Record<string, any> = {}): string {
  if (type === 'join') return fields.how === 'left' ? 'join_left' : 'join';
  return type;
}
