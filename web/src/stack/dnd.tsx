// Drag and drop: palette → workspace, blocks between stacks, condition pills → slots.
import {
  DndContext, DragOverlay, PointerSensor, KeyboardSensor, rectIntersection, useSensor, useSensors,
  type CollisionDetection, type DragEndEvent, type DragStartEvent,
} from '@dnd-kit/core';
import { useState, type ReactNode } from 'react';
import { find, insertBlock, loopVars, moveBlock, SINGLE, walk } from '../ir';
import { useStore } from '../store';
import type { Block, Program } from '../types';
import { makeExpr } from './Expr';
import type { Scope } from './fields';
import { makeBlock } from './make';

export interface DragData {
  kind: 'new' | 'table' | 'move' | 'expr';
  family: 'step' | 'statement' | 'expr';
  type?: string;
  table?: string;
  id?: string;
  label: string;
}

// The real pointer position. dnd-kit's own pointer coordinates are scroll-adjusted, which goes
// wrong when the palette and the workspace scroll separately, so we hit-test live rectangles.
const pointer = { x: -1, y: -1 };
if (typeof window !== 'undefined') {
  window.addEventListener('pointermove', (e) => {
    pointer.x = e.clientX;
    pointer.y = e.clientY;
  }, { capture: true, passive: true });
}

/** Drop onto the smallest target under the pointer that accepts the dragged kind of block. */
const collide: CollisionDetection = (args) => {
  const family = args.active.data.current?.family;
  const ok = args.droppableContainers.filter((c) => {
    const d = c.data.current as any;
    return d?.kind === 'slot' ? family === 'expr' : d?.accepts === family;
  });
  const hits = ok.map((c) => {
    const r = c.node.current?.getBoundingClientRect();
    if (!r || pointer.x < r.left || pointer.x > r.right || pointer.y < r.top || pointer.y > r.bottom) return null;
    return { id: c.id, data: { droppableContainer: c, value: r.width * r.height } };
  }).filter((h): h is NonNullable<typeof h> => h !== null).sort((p, q) => p.data.value - q.data.value);
  return hits.length ? hits : rectIntersection({ ...args, droppableContainers: ok });
};

function contains(block: Block, id: string): boolean {
  for (const b of walk([block])) if (b.id === id) return true;
  return false;
}

export function DndProvider({ children }: { children: ReactNode }) {
  const { state, dispatch } = useStore();
  const [dragging, setDragging] = useState<DragData | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor),
  );

  const onStart = (e: DragStartEvent) => {
    setDragging((e.active.data.current as DragData) ?? null);
    document.body.classList.add('dragging-on');
  };

  const onEnd = (e: DragEndEvent) => {
    setDragging(null);
    document.body.classList.remove('dragging-on');
    const a = e.active.data.current as DragData | undefined;
    const o = e.over?.data.current as any;
    if (!a || !o) return;
    const tables = state.project?.tables ?? [];
    if (o.kind === 'slot') {
      if (a.kind === 'expr' && a.type) o.set(makeExpr(a.type, o.scope as Scope));
      return;
    }
    if (o.kind !== 'gap' || o.accepts !== a.family) return;
    const apply = (p: Program): Program => {
        const from = o.stack === 'steps' ? find(p, o.parent) : null;
        if (a.kind === 'move' && a.id) {
          const moving = find(p, a.id);
          if (!moving || (o.parent && contains(moving, o.parent))) return p;
          if (from && SINGLE.has(moving.type) && (from.stacks.steps ?? []).some((s) => s.type === moving.type && s.id !== moving.id)) {
            dispatch({ type: 'toast', message: `Only one ${moving.type} block fits in a stack.` });
            return p;
          }
          return moveBlock(p, a.id, o.parent, o.stack, o.index);
        }
        if (a.kind === 'new' && a.type) {
          if (from && SINGLE.has(a.type) && (from.stacks.steps ?? []).some((s) => s.type === a.type)) {
            dispatch({ type: 'toast', message: `Only one ${a.label} block fits in a stack.` });
            return p;
          }
          const lv = o.parent ? loopVars(p, o.parent) : [];
          const parentBlock = o.parent ? find(p, o.parent) : null;
          const loop = parentBlock?.type === 'foreach'
            ? { name: parentBlock.fields.var || 'row', over: parentBlock.inputs.over?.fields?.name ?? null }
            : lv[lv.length - 1] ?? null;
          const b = makeBlock(a.type, p, tables, { from, loopVar: loop });
          dispatch({ type: 'focus', id: b.id });
          return insertBlock(p, b, o.parent, o.stack, o.index);
        }
        if (a.kind === 'table' && a.table) {
          const b = makeBlock('from', p, tables, { table: a.table });
          return insertBlock(p, b, o.parent, o.stack, o.index);
        }
        return p;
    };
    const next = apply(state.program);
    if (next !== state.program) dispatch({ type: 'program', program: next });
  };

  return (
    <DndContext sensors={sensors} collisionDetection={collide} onDragStart={onStart} onDragEnd={onEnd}
      autoScroll={{ canScroll: (el) => el.classList.contains('workspace') }}
      onDragCancel={() => { setDragging(null); document.body.classList.remove('dragging-on'); }}>
      {children}
      <DragOverlay dropAnimation={null}>
        {dragging ? <div className="drag-ghost">{dragging.label}</div> : null}
      </DragOverlay>
    </DndContext>
  );
}
