"""Plan → pandas. One reassignment line per block, so every line maps back to one block.

CSVs are read with ``dtype_backend="numpy_nullable"`` so empty values stay <NA> and comparisons
follow SQL's rules: a row whose value is empty is never kept by a filter.
"""

from __future__ import annotations

from blockcode.codegen.emitter import Emitter
from blockcode.codegen.expr import (ExprError, PandasRenderer, checked_name, py_kwarg, py_str,
                                    whole)
from blockcode.ir import TableInfo
from blockcode.plan import Plan

PD_AGG = {"count": "count", "sum": "sum", "avg": "mean", "min": "min", "max": "max"}


def read_csv_line(table: str, tables: dict[str, TableInfo], block_id: str | None = None) -> str:
    info = tables.get(table)
    path = info.file if info else f"data/{table}.csv"
    return (f"{checked_name(table, block_id)} = "
            f'pd.read_csv({py_str(path)}, dtype_backend="numpy_nullable")')


def emit_pipeline(em: Emitter, plan: Plan, tables: dict[str, TableInfo], loaded: set[str]) -> None:
    """Emit the read_csv lines this stack still needs, then one line per block."""
    for b, table in [(plan.block, plan.table)] + [(j, j.field("table")) for j in plan.joins]:
        if table and table not in loaded:
            em.emit(read_csv_line(table, tables, b.id), b.id)
            loaded.add(table)
    em.blank()

    out = checked_name(plan.name, plan.block.id)
    r = PandasRenderer(out)
    em.emit(f"{out} = {checked_name(plan.table, plan.block.id)}", plan.block.id)
    for j in plan.joins:
        how = ', how="left"' if j.field("how") == "left" else ""
        right = checked_name(j.field("table"), j.id)
        em.emit(f'{out} = {out}.merge({right}, on={py_str(str(j.field("on")))}{how})', j.id)
    for d in plan.derives:
        em.emit(f"{out} = {out}.assign({py_kwarg(d.field('name'), r(d.inputs.get('expr')))})", d.id)
    for w in plan.wheres:
        em.emit(f"{out} = {out}[{r(w.inputs.get('cond'))}]", w.id)
    if plan.group:
        emit_group(em, plan, out)
    if plan.having:
        em.emit(f"{out} = {out}[{r(plan.having.inputs.get('cond'))}]", plan.having.id)
    if plan.select:
        cols = ", ".join(py_str(c) for c in plan.select.field("columns", []))
        em.emit(f"{out} = {out}[[{cols}]]", plan.select.id)
    if plan.order:
        keys = plan.order.field("keys", [])
        if len(keys) == 1:
            k = keys[0]
            asc = ", ascending=False" if k.get("desc") else ""
            em.emit(f"{out} = {out}.sort_values({py_str(k['column'])}{asc})", plan.order.id)
        else:
            cols = ", ".join(py_str(k["column"]) for k in keys)
            ascs = ", ".join("False" if k.get("desc") else "True" for k in keys)
            em.emit(f"{out} = {out}.sort_values([{cols}], ascending=[{ascs}])", plan.order.id)
    # a LIMIT that isn't a whole number is reported by the plan and left out of the code
    if plan.limit and whole(plan.limit.field("n")) is not None:
        em.emit(f"{out} = {out}.head({whole(plan.limit.field('n'))})", plan.limit.id)


def emit_group(em: Emitter, plan: Plan, out: str) -> None:
    g = plan.group
    assert g is not None
    by = g.field("by", [])
    aggs = g.field("aggs", [])
    if not by:
        # A summary of the whole table: one row.
        em.emit(f"{out} = pd.DataFrame({{", g.id)
        for a in aggs:
            em.emit(f"    {py_str(a.get('as') or '')}: [{whole_agg(a, out)}],", g.id)
        em.emit("})", g.id)
        return
    keys = py_str(by[0]) if len(by) == 1 else "[" + ", ".join(py_str(k) for k in by) + "]"
    if not aggs:
        em.emit(f"{out} = {out}[{'[' + ', '.join(py_str(k) for k in by) + ']'}]"
                f".drop_duplicates()", g.id)
        return
    em.emit(f"{out} = {out}.groupby({keys}, as_index=False, dropna=False).agg(", g.id)
    others = [c for c in plan.pre_group if c not in by]
    for a in aggs:
        if a.get("func") == "count" and not a.get("column"):
            # COUNT(*) counts rows, empty or not: "size" on any column does the same.
            col, fn = (others[0] if others else by[0]), "size"
        else:
            col, fn = a.get("column") or "", pd_agg(a)
        em.emit(f"    {py_kwarg(a.get('as') or '', f'({py_str(col)}, {py_str(fn)})')},", g.id)
    em.emit(")", g.id)


def pd_agg(a: dict) -> str:
    fn = PD_AGG.get(a.get("func"))
    if fn is None:  # the plan has already said why
        raise ExprError("Pick a summary: count, sum, avg, min or max.")
    return fn


def whole_agg(a: dict, out: str) -> str:
    if a.get("func") == "count" and not a.get("column"):
        return f"len({out})"
    return f"{out}[{py_str(a.get('column') or '')}].{pd_agg(a)}()"
