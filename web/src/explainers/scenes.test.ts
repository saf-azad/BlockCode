import { poseAt, sceneFor, scenes } from './scenes';
import stories from './stories.json';

const visibleAt = (tag: string, scene: ReturnType<typeof scenes>[string], t: number) =>
  scene.cubes.filter((c) => c.tag === tag && poseAt(c.kf, t).o > 0.5).length;

describe('hover animations', () => {
  const sc = scenes('sql');
  const settle = (name: string) => sc[name].L - 0.6; // after the action, before the fade-out

  test('every Python/R and data block has a scene', () => {
    for (const t of ['from', 'join', 'join_left', 'where', 'derive', 'group', 'having', 'select', 'order', 'limit',
      'plot', 'foreach', 'print', 'repeat', 'if', 'while', 'setvar', 'changevar', 'raw']) {
      expect(sc[t], t).toBeTruthy();
    }
  });

  test('inner join keeps only matching pairs', () => {
    const s = sc.join;
    const t = settle('join');
    const left = s.cubes.filter((c) => c.tag?.startsWith('L') && poseAt(c.kf, t).o > 0.5).length;
    const right = s.cubes.filter((c) => c.tag?.startsWith('R') && poseAt(c.kf, t).o > 0.5).length;
    expect(left).toBe(stories.join_inner.rows);
    expect(right).toBe(stories.join_inner.rows);
    expect(s.cubes.some((c) => c.tag?.startsWith('E'))).toBe(false);
  });

  test('left join keeps every left row and adds hollow partners', () => {
    const s = sc.join_left;
    const t = settle('join_left');
    const left = s.cubes.filter((c) => c.tag?.startsWith('L') && poseAt(c.kf, t).o > 0.5).length;
    const empty = s.cubes.filter((c) => c.tag?.startsWith('E') && poseAt(c.kf, t).o > 0.5);
    expect(left).toBe(stories.join_left.left.length);
    expect(empty.length).toBe(stories.join_left.empty_partners);
    expect(poseAt(empty[0].kf, t).f.toLowerCase()).toBe('#ffffff');
  });

  test('matched rows end up side by side on the same row', () => {
    const s = sc.join;
    const t = settle('join');
    for (const k of ['A', 'C']) {
      const l = poseAt(s.cubes.find((c) => c.tag === `L${k}`)!.kf, t);
      const r = poseAt(s.cubes.find((c) => c.tag === `R${k}`)!.kf, t);
      expect(l.y).toBeCloseTo(r.y);
      expect(r.x - l.x).toBeCloseTo(1);
    }
  });

  test('where, limit, having and select show the right number of rows', () => {
    expect(visibleAt('kept', sc.where, settle('where'))).toBe(stories.where.kept.length);
    expect(visibleAt('dropped', sc.where, settle('where'))).toBe(0);
    expect(visibleAt('kept', sc.limit, settle('limit'))).toBe(stories.limit.n);
    expect(visibleAt('dropped', sc.limit, settle('limit'))).toBe(0);
    expect(visibleAt('group', sc.group, settle('group'))).toBe(stories.group.groups);
    expect(visibleAt('dropped', sc.having, settle('having'))).toBe(0);
    expect(visibleAt('kept', sc.select, settle('select'))).toBe(stories.select.rows * stories.select.keep.length);
  });

  test('join picks the scene from its setting', () => {
    expect(sceneFor('join', { how: 'left' })).toBe('join_left');
    expect(sceneFor('join', { how: 'inner' })).toBe('join');
    expect(sceneFor('where')).toBe('where');
  });

  test('every scene loops: cubes are invisible at the very end', () => {
    for (const [name, s] of Object.entries(sc)) {
      for (const c of s.cubes) expect(poseAt(c.kf, s.L).o, name).toBeLessThan(0.05);
    }
  });
});
