"""Plan → SQLite. One SELECT statement per From stack; each clause line is tagged with its block."""

from __future__ import annotations

from blockcode.codegen.emitter import Emitter, Generated
from blockcode.codegen.expr import ATOM, ExprError, SqlRenderer, sql_ident
from blockcode.diagnostics import Diagnostic, error
from blockcode.ir import Block, Program, TableInfo
from blockcode.plan import Plan, build_plan, nullable
from blockcode.registry import SPECS

SQL_AGG = {"count": "COUNT", "sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}


def generate_sql(program: Program, tables: dict[str, TableInfo]) -> Generated:
    em = Emitter(indent="  ")
    diags: list[Diagnostic] = []
    ok = True
    for top in program.blocks:
        if top.type == "from":
            plan = build_plan(top, tables)
            diags += plan.diagnostics
            em.blank()
            try:
                emit_select(em, plan)
            except ExprError as exc:
                diags.append(error(str(exc), exc.block_id or top.id, target="sql"))
        elif top.type == "plot":
            diags.append(Diagnostic(severity="info", block_id=top.id, target="sql",
                                    message="SQL has no plotting, so this plot is detached. "
                                            "Switch to Python or R to draw it."))
        else:
            ok = False
            for b in top.walk():
                spec = SPECS.get(b.type)
                if spec and not spec.sql_ok and spec.family != "expr":
                    label = spec.labels["python"].lower()
                    diags.append(Diagnostic(severity="sql", block_id=b.id, target="sql",
                                            message=f"{label} has no SQL equivalent."))
    return em.result("sql", diags, ok=ok)


def agg_sql(a: dict, render) -> str:
    func = SQL_AGG.get(a.get("func"), str(a.get("func")).upper())
    column = a.get("column")
    if not column:
        return f"{func}(*)"
    return f"{func}({render(column)})"


def emit_select(em: Emitter, plan: Plan) -> None:
    derived = {d.field("name"): d for d in plan.derives}
    types = {c.name: c.type for c in plan.pre_group.values()}

    def resolve_pre(name: str) -> tuple[str, int] | None:
        d = derived.get(name)
        if d is None:
            return None
        return pre.render(d.inputs.get("expr"))

    pre = SqlRenderer(resolve_pre, types)

    def col_pre(name: str) -> str:
        got = resolve_pre(name)
        return got[0] if got else sql_ident(name)

    # SELECT list: (text, blocks)
    items: list[tuple[str, list[str]]] = []
    group = plan.group
    if group:
        for key in group.field("by", []):
            d = derived.get(key)
            text = f"{pre(d.inputs.get('expr'))} AS {sql_ident(key)}" if d else sql_ident(key)
            items.append((text, [group.id] + ([d.id] if d else [])))
        for a in group.field("aggs", []):
            items.append((f"{agg_sql(a, col_pre)} AS {sql_ident(a.get('as', ''))}", [group.id]))
        if plan.select:
            keep = plan.select.field("columns", [])
            names = list(group.field("by", [])) + [a.get("as") for a in group.field("aggs", [])]
            by_name = dict(zip(names, items))
            items = [(by_name[c][0], by_name[c][1] + [plan.select.id]) for c in keep
                     if c in by_name]
    elif plan.select:
        for c in plan.select.field("columns", []):
            d = derived.get(c)
            if d:
                items.append((f"{pre(d.inputs.get('expr'))} AS {sql_ident(c)}",
                              [plan.select.id, d.id]))
            else:
                items.append((sql_ident(c), [plan.select.id]))
    else:
        items.append(("*", [plan.block.id]))
        for d in plan.derives:
            items.append((f"{pre(d.inputs.get('expr'))} AS {sql_ident(d.field('name'))}", [d.id]))

    for i, (text, blocks) in enumerate(items):
        lead = "SELECT " if i == 0 else "       "
        tail = "," if i < len(items) - 1 else ""
        em.emit(lead + text + tail, *blocks)

    em.emit(f"FROM {sql_ident(plan.table)}", plan.block.id)
    for j in plan.joins:
        kw = "LEFT JOIN" if j.field("how") == "left" else "JOIN"
        em.emit(f"{kw} {sql_ident(j.field('table'))} USING ({sql_ident(j.field('on'))})", j.id)
    for i, w in enumerate(plan.wheres):
        text, prec = pre.render(w.inputs.get("cond"))
        if len(plan.wheres) > 1 and prec < pre.prec["and"]:
            text = f"({text})"
        em.emit(("WHERE " if i == 0 else "  AND ") + text, w.id)
    if group and group.field("by"):
        shown = set(plan.select.field("columns", [])) if plan.select else None
        keys = []
        for k in group.field("by", []):
            d = derived.get(k)
            # a new column used only for grouping isn't in the SELECT list, so repeat its sum
            keys.append(pre(d.inputs.get("expr")) if d and shown is not None and k not in shown
                        else sql_ident(k))
        em.emit("GROUP BY " + ", ".join(keys), group.id)
    if plan.having:
        aggs = {a.get("as"): a for a in group.field("aggs", [])} if group else {}

        def resolve_post(name: str) -> tuple[str, int] | None:
            a = aggs.get(name)
            return (agg_sql(a, col_pre), ATOM) if a else None

        em.emit("HAVING " + SqlRenderer(resolve_post)(plan.having.inputs.get("cond")),
                plan.having.id)
    if plan.order:
        parts = []
        for k in plan.order.field("keys", []):
            c = k.get("column", "")
            if k.get("desc"):
                parts.append(f"{sql_ident(c)} DESC")
            elif nullable(plan, c):
                # SQLite sorts empty values first; pandas and dplyr put them last.
                parts.append(f"{sql_ident(c)} NULLS LAST")
            else:
                parts.append(sql_ident(c))
        em.emit("ORDER BY " + ", ".join(parts), plan.order.id)
    if plan.limit:
        em.emit(f"LIMIT {plan.limit.field('n')}", plan.limit.id)
    # close the statement
    text, blocks = em._lines[-1]
    em._lines[-1] = (text + ";", blocks)
