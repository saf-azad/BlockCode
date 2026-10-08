"""Per-target checks: everything the code generators report, plus variable use before set."""

from __future__ import annotations

from blockcode.codegen import generate
from blockcode.diagnostics import Diagnostic, error, warning
from blockcode.ir import Block, Program, TableInfo
from blockcode.plan import Plan, build_plan

NUMERIC = ("int", "float")
# Bars past this many draw slowly and can't be read; a histogram or Group by is the fix.
MAX_BARS = 100


def validate(program: Program, tables: dict[str, TableInfo], target: str,
             generated=None) -> list[Diagnostic]:
    gen = generated if generated is not None else generate(program, tables, target)
    diags = list(gen.diagnostics)
    if target != "sql":
        diags += check_variables(program)
        diags += check_plots(program, tables)
    seen: set[tuple] = set()
    out = []
    for d in diags:
        key = (d.severity, d.message, d.block_id)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def check_variables(program: Program) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    def uses(b: Block | None) -> list[tuple[str, Block]]:
        if b is None:
            return []
        out = []
        for x in b.walk():
            if x.type == "var":
                out.append((x.field("name"), x))
            elif x.type == "field":
                out.append((x.field("var"), x))
        return out

    def check(owner: Block, expr: Block | None, known: set[str]) -> None:
        for name, _ in uses(expr):
            if name and name not in known:
                diags.append(warning(f"{name} is used before it has a value. Add a Set var "
                                     f"block above it, or pick a column instead.", owner.id))

    def walk(blocks: list[Block], known: set[str]) -> None:
        for b in blocks:
            t = b.type
            if t == "from":
                known.add(b.field("name") or "out")
            elif t == "setvar":
                check(b, b.inputs.get("value"), known)
                known.add(b.field("name"))
            elif t == "changevar":
                if b.field("name") not in known:
                    diags.append(error(f"{b.field('name')} needs a Set var block before it can "
                                       f"change.", b.id))
                check(b, b.inputs.get("by"), known)
            elif t in ("foreach", "repeat"):
                check(b, b.inputs.get("over") or b.inputs.get("times"), known)
                inner = set(known) | {b.field("var") or ("row" if t == "foreach" else "i")}
                walk(b.stack("body"), inner)
                known |= inner - {b.field("var")}
            elif t in ("if", "while"):
                check(b, b.inputs.get("cond"), known)
                walk(b.stack("body"), known)
                walk(b.stack("else"), known)
            elif t == "print":
                for v in b.inputs.values():
                    check(b, v, known)
            elif t == "plot":
                data = b.field("data") or "out"
                if data not in known:
                    diags.append(error(f"{data} has no rows yet. Put the plot below a stack.",
                                       b.id))
    walk(program.blocks, set())
    return diags


def check_plots(program: Program, tables: dict[str, TableInfo]) -> list[Diagnostic]:
    """Catch the plots that would crash or hang before they run: a column the rows don't have,
    text where the chart needs numbers, and a bar for every one of thousands of rows."""
    diags: list[Diagnostic] = []
    plans: dict[str, Plan] = {}
    for b in program.walk():  # source order, so a plot sees the stacks above it
        if b.type == "from":
            plans[b.field("name") or "out"] = build_plan(b, tables)
        elif b.type == "plot":
            plan = plans.get(b.field("data") or "out")
            if plan is not None and plan.known:
                diags += _check_plot(b, plan, tables)
    return diags


def _check_plot(b: Block, plan: Plan, tables: dict[str, TableInfo]) -> list[Diagnostic]:
    chart, x, y = b.field("chart", "bar"), b.field("x"), b.field("y")
    cols, data = plan.columns, plan.name
    out: list[Diagnostic] = []
    axes = [("x", x)] if chart == "hist" else [("x", x), ("y", y)]
    for axis, name in axes:
        if name and name not in cols:
            out.append(error(f"{data} has no column called {name} any more. Pick another column "
                             f"for the {axis} axis.", b.id))
    if out:
        return out

    if not any(c.type in NUMERIC or c.type == "any" for c in cols.values()):
        return [error(f"{data} has no number columns to plot. Group the rows and count them "
                      f"(or add a new column), then plot that.", b.id)]

    def needs_number(name: str, what: str) -> None:
        c = cols.get(name)
        if c is not None and c.type not in NUMERIC and c.type != "any":
            kind = "true/false" if c.type == "bool" else "text"
            out.append(error(f"{what} needs numbers, but {name} is {kind}. Pick a number column"
                             f"{' or a bar chart' if what.startswith('A scatter') else ''}.",
                             b.id))

    if chart == "hist":
        if x:
            needs_number(x, "A histogram")
    else:
        if y:
            needs_number(y, "The y axis")
        if chart == "scatter" and x:
            needs_number(x, "A scatter plot's x axis")
    if chart == "bar" and not out:
        rows = _row_estimate(plan, tables)
        if rows is not None and rows > MAX_BARS:
            out.append(error(f"This draws one bar for each of the {rows:,} rows in {data}, which "
                             f"is too many to read. Group the rows first, keep fewer of them, or "
                             f"switch to a histogram.", b.id))
    return out


def _row_estimate(plan: Plan, tables: dict[str, TableInfo]) -> int | None:
    """Rows the stack will have, when that's certain without running it."""
    if plan.wheres or plan.joins or plan.having:
        return None
    if plan.group is not None:
        return 1 if not plan.group.field("by", []) else None
    info = tables.get(plan.table)
    if info is None:
        return None
    rows = info.rows
    if plan.limit is not None and isinstance(plan.limit.field("n"), int):
        rows = min(rows, plan.limit.field("n"))
    return rows
