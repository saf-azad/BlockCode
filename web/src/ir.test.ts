import { clauseOrder, columnsAt, hasPythonOnly, insertBlock, mk, moveBlock, parseLiteral, removeBlock, setField, walk } from './ir';
import type { Program, TableInfo } from './types';

const tables: TableInfo[] = [
  { name: 'enrolments', file: 'data/enrolments.csv', rows: 3, columns: [
    { name: 'student_id', type: 'int', empty: 0 }, { name: 'course_id', type: 'text', empty: 0 }, { name: 'grade', type: 'float', empty: 1 }] },
  { name: 'courses', file: 'data/courses.csv', rows: 2, columns: [
    { name: 'course_id', type: 'text', empty: 0 }, { name: 'dept', type: 'text', empty: 0 }] },
];

function program(): { p: Program; from: ReturnType<typeof mk> } {
  const from = mk('from', { table: 'enrolments', name: 'out' }, {}, {
    steps: [mk('join', { table: 'courses', on: 'course_id', how: 'inner' }), mk('limit', { n: 5 })],
  });
  return { p: { blocks: [from] }, from };
}

test('steps stay in clause order when inserted', () => {
  const { p, from } = program();
  const where = mk('where');
  const next = insertBlock(p, where, from.id, 'steps', 99);
  expect(next.blocks[0].stacks.steps.map((b) => b.type)).toEqual(['join', 'where', 'limit']);
  expect(clauseOrder([mk('limit'), mk('group'), mk('join')]).map((b) => b.type)).toEqual(['join', 'group', 'limit']);
});

test('columns flow through join, group and select', () => {
  const { from } = program();
  expect(columnsAt(from, 0, tables).map((c) => c.name)).toEqual(['student_id', 'course_id', 'grade']);
  expect(columnsAt(from, 1, tables).map((c) => c.name)).toEqual(['student_id', 'course_id', 'grade', 'dept']);
  const grouped = mk('from', { table: 'enrolments' }, {}, {
    steps: [mk('group', { by: ['course_id'], aggs: [{ func: 'avg', column: 'grade', as: 'avg' }] }), mk('select', { columns: ['avg'] })],
  });
  expect(columnsAt(grouped, 1, tables).map((c) => c.name)).toEqual(['course_id', 'avg']);
  expect(columnsAt(grouped, 2, tables).map((c) => c.name)).toEqual(['avg']);
});

test('edit helpers are immutable', () => {
  const { p, from } = program();
  const lim = from.stacks.steps[1];
  const q = setField(p, lim.id, 'n', 3);
  expect(p.blocks[0].stacks.steps[1].fields.n).toBe(5);
  expect(q.blocks[0].stacks.steps[1].fields.n).toBe(3);
  const r = removeBlock(q, lim.id);
  expect([...walk(r.blocks)].some((b) => b.id === lim.id)).toBe(false);
});

test('moving a statement into a loop body', () => {
  const pr = mk('print');
  const loop = mk('foreach', { var: 'row' }, { over: mk('var', { name: 'out' }) }, { body: [] });
  const p: Program = { blocks: [loop, pr] };
  const q = moveBlock(p, pr.id, loop.id, 'body', 0);
  expect(q.blocks.length).toBe(1);
  expect(q.blocks[0].stacks.body[0].id).toBe(pr.id);
  expect(hasPythonOnly(q)).toBe(true);
  expect(hasPythonOnly(program().p)).toBe(false);
});

test('literals typed by learners', () => {
  expect(parseLiteral('50')).toBe(50);
  expect(parseLiteral('2.5')).toBe(2.5);
  expect(parseLiteral('S1')).toBe('S1');
  expect(parseLiteral('"42"')).toBe('42');
  expect(parseLiteral('true')).toBe(true);
});
