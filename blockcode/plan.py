"""Turn a From stack into a relational plan and track the columns at every stage.

    Source → Join* → Derive* → Where* → Group/Agg → Having → Select → Order → Limit

Every code generator walks the same plan, which is what makes SQL, pandas and dplyr agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from blockcode.codegen.expr import whole
from blockcode.diagnostics import Diagnostic, error, warning
from blockcode.ir import Block, TableInfo
from blockcode.registry import SPECS, STEP_ORDER

AGG_FUNCS = ("count", "sum", "avg", "min", "max")


@dataclass
class Col:
    name: str
    type: str  # "int" | "float" | "text" | "bool" | "any"
    nullable: bool = False


@dataclass
class Plan:
    block: Block
    name: str
    table: str
    joins: list[Block] = field(default_factory=list)
    wheres: list[Block] = field(default_factory=list)
    derives: list[Block] = field(default_factory=list)
    group: Block | None = None
    having: Block | None = None
    select: Block | None = None
    order: Block | None = None
    limit: Block | None = None
    # columns visible to Where/Derive (before grouping) and after the whole pipeline
    pre_group: dict[str, Col] = field(default_factory=dict)
    post_group: dict[str, Col] = field(default_factory=dict)
    columns: dict[str, Col] = field(default_factory=dict)
    known: bool = True  # False when a table's columns are unknown (skip column checks)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def tables(self) -> list[str]:
        return [self.table] + [j.field("table") for j in self.joins]

    def steps(self) -> list[Block]:
        out: list[Block] = [*self.joins, *self.derives, *self.wheres]
        out += [b for b in (self.group, self.having, self.select, self.order, self.limit) if b]
        return out

    def derived(self, name: str) -> Block | None:
        return next((d.inputs.get("expr") for d in self.derives if d.field("name") == name), None)

    def agg(self, alias: str) -> dict | None:
        if not self.group:
            return None
        return next((a for a in self.group.field("aggs", []) if a.get("as") == alias), None)


def expr_columns(expr: Block | None) -> list[tuple[str, Block]]:
    """Column references inside an expression, with the block that references them."""
    if expr is None:
        return []
    return [(b.field("name"), b) for b in expr.walk() if b.type == "col"]


def expr_type(expr: Block | None, cols: dict[str, Col]) -> Col:
    if expr is None:
        return Col("", "any")
    t = expr.type
    if t == "col":
        c = cols.get(expr.field("name"))
        return Col("", c.type, c.nullable) if c else Col("", "any", True)
    if t == "lit":
        v = expr.field("value")
        if v is None:
            return Col("", "any", True)
        if isinstance(v, bool):
            return Col("", "bool")
        if isinstance(v, int):
            return Col("", "int")
        if isinstance(v, float):
            return Col("", "float")
        return Col("", "text")
    if t == "math":
        a, b = expr_type(expr.inputs.get("a"), cols), expr_type(expr.inputs.get("b"), cols)
        nullable = a.nullable or b.nullable
        if expr.field("op") == "/" or "float" in (a.type, b.type):
            return Col("", "float", nullable)
        return Col("", "int" if a.type == b.type == "int" else "any", nullable)
    # comparisons, logic, is empty, in list, text tests
    nullable = any(c.nullable for c in (expr_type(x, cols) for x in expr.inputs.values()))
    return Col("", "bool", nullable and t != "isempty")


def _agg_col(a: dict, cols: dict[str, Col]) -> Col:
    func, column = a.get("func"), a.get("column")
    src = cols.get(column) if column else None
    if func == "count":
        return Col(a.get("as", ""), "int")
    if func == "avg":
        return Col(a.get("as", ""), "float", bool(src and src.nullable))
    t = src.type if src else "any"
    return Col(a.get("as", ""), t, bool(src and src.nullable))


def build_plan(src: Block, tables: dict[str, TableInfo]) -> Plan:
    plan = Plan(block=src, name=src.field("name") or "out", table=src.field("table") or "")
    diags = plan.diagnostics

    if not plan.table:
        diags.append(error("Pick a table for this From block.", src.id))
        plan.known = False
    cols: dict[str, Col] = {}
    info = tables.get(plan.table)
    if info:
        cols = {c.name: Col(c.name, c.type, c.empty > 0) for c in info.columns}
    elif plan.table:
        diags.append(error(f'There is no table called "{plan.table}". Drop a CSV to add it.',
                           src.id))
        plan.known = False

    # Sort steps into clause order, keeping the order of repeated blocks.
    steps = src.stack("steps")
    rank = {t: i for i, t in enumerate(STEP_ORDER)}
    ordered = sorted(steps, key=lambda b: rank.get(b.type, len(rank)))
    if [b.id for b in ordered] != [b.id for b in steps]:
        diags.append(warning("Blocks were moved into clause order (JOIN, new column, WHERE, "
                             "GROUP BY, "
                             "HAVING, SELECT, ORDER BY, LIMIT).", src.id))

    def check(expr: Block | None, scope: dict[str, Col], owner: Block, where: str) -> None:
        if expr is None:
            diags.append(error(f"{_label(owner)} needs a condition.", owner.id))
            return
        for b in expr.walk():
            if b.type == "col" and plan.known and b.field("name") not in scope:
                diags.append(error(f'"{b.field("name")}" is not a column {where}.', owner.id))
            elif b.type in ("var", "field"):
                diags.append(error(f"{_label(owner)} can only use columns, not variables.",
                                   owner.id))

    pre_group_set = False
    for b in ordered:
        if not pre_group_set and b.type in ("group", "having", "select", "order", "limit"):
            plan.pre_group, pre_group_set = dict(cols), True
        spec = SPECS.get(b.type)
        if spec is None or spec.family != "step":
            diags.append(error(f'"{b.type}" can\'t go inside a From stack.', b.id))
            continue
        if spec.single and getattr(plan, b.type) is not None:
            diags.append(error(f"Only one {_label(b)} block fits in a stack.", b.id))
            continue

        if b.type == "join":
            table, key = b.field("table"), b.field("on")
            how = b.field("how", "inner")
            right = tables.get(table)
            if not right:
                diags.append(error(f'There is no table called "{table}".', b.id))
                plan.known = False
            else:
                if plan.known and key not in cols:
                    diags.append(error(f'"{key}" is not a column of the rows so far.', b.id))
                if not right.column(key):
                    diags.append(error(f'"{key}" is not a column of {table}.', b.id))
                for c in right.columns:
                    if c.name == key:
                        continue
                    if c.name in cols:
                        diags.append(warning(
                            f'Both tables have a column called "{c.name}". Pick one with a '
                            f"Select block, or rename it first.", b.id))
                    cols[c.name] = Col(c.name, c.type, c.empty > 0 or how == "left")
            plan.joins.append(b)
        elif b.type == "where":
            check(b.inputs.get("cond"), cols, b, "here")
            plan.wheres.append(b)
        elif b.type == "derive":
            name = b.field("name")
            if not name:
                diags.append(error("Give the new column a name.", b.id))
            check(b.inputs.get("expr"), cols, b, "here")
            t = expr_type(b.inputs.get("expr"), cols)
            if name:
                cols[name] = Col(name, t.type, t.nullable)
            plan.derives.append(b)
        elif b.type == "group":
            new: dict[str, Col] = {}
            for key in b.field("by", []):
                if plan.known and key not in cols:
                    diags.append(error(f'"{key}" is not a column here.', b.id))
                new[key] = cols.get(key, Col(key, "any", True))
            for a in b.field("aggs", []):
                if a.get("func") not in AGG_FUNCS:
                    diags.append(error(f'"{a.get("func")}" is not a summary I know.', b.id))
                if a.get("func") != "count" and not a.get("column"):
                    diags.append(error(f"{a.get('func')} needs a column.", b.id))
                if a.get("column") and plan.known and a["column"] not in cols:
                    diags.append(error(f'"{a["column"]}" is not a column here.', b.id))
                if not a.get("as"):
                    diags.append(error("Give each summary a name.", b.id))
                new[a.get("as", "")] = _agg_col(a, cols)
            if not new:
                diags.append(error("Group by needs a column or a summary.", b.id))
            cols = new
            plan.group = b
        elif b.type == "having":
            if plan.group is None:
                diags.append(error("HAVING needs a Group by block above it.", b.id))
            check(b.inputs.get("cond"), cols, b, "after grouping")
            plan.having = b
        elif b.type == "select":
            chosen = b.field("columns", [])
            if not chosen:
                diags.append(error("Pick at least one column to keep.", b.id))
            for c in chosen:
                if plan.known and c not in cols:
                    diags.append(error(f'"{c}" is not a column here.', b.id))
            cols = {c: cols.get(c, Col(c, "any", True)) for c in chosen}
            plan.select = b
        elif b.type == "order":
            keys = b.field("keys", [])
            if not keys:
                diags.append(error("Pick a column to sort by.", b.id))
            for k in keys:
                if plan.known and k.get("column") not in cols:
                    diags.append(error(f'"{k.get("column")}" is not a column here.', b.id))
            plan.order = b
        elif b.type == "limit":
            if whole(b.field("n")) is None:
                diags.append(error("LIMIT needs a whole number of rows.", b.id))
            plan.limit = b

    if not pre_group_set:
        plan.pre_group = dict(cols)
    used = None
    if plan.group is not None:
        used = set(plan.group.field("by", [])) | {a.get("column") for a in
                                                  plan.group.field("aggs", [])}
    elif plan.select is not None:
        used = set(plan.select.field("columns", []))
    if used is not None:
        for d in plan.derives:
            if d.field("name") and d.field("name") not in used:
                why = "Group by doesn't use" if plan.group is not None else "Select doesn't keep"
                diags.append(warning(f'{d.field("name")} is worked out but {why} it, so it '
                                     f"won't be in the result.", d.id))
    plan.post_group = dict(cols)
    plan.columns = cols
    return plan


def _label(b: Block) -> str:
    spec = SPECS.get(b.type)
    return spec.labels["sql"] if spec and spec.labels["sql"] != "—" else b.type


def nullable(plan: Plan, column: str) -> bool:
    c = plan.columns.get(column)
    return True if c is None else c.nullable
