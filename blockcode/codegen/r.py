"""Program → R (dplyr). The Code tab shows a Quarto document; export also writes a plain .R.

Pipelines are one ``|>`` chain with one verb per block, so each line maps back to one block.
"""

from __future__ import annotations

import re

from blockcode.codegen.emitter import Emitter, Generated
from blockcode.codegen.expr import ExprError, RRenderer, one_line, py_str, r_ident, r_name, whole
from blockcode.diagnostics import Diagnostic, error
from blockcode.ir import Block, Program, TableInfo
from blockcode.plan import Plan, build_plan

GEOMS = {"bar": "geom_col()", "line": "geom_line(aes(group = 1)) + geom_point()",
         "scatter": "geom_point()"}


def generate_r(program: Program, tables: dict[str, TableInfo], quarto: bool = True,
               title: str = "BlockCode") -> Generated:
    return _RGen(program, tables, quarto, title).run()


def _agg_r(a: dict) -> str:
    func, column = a.get("func"), a.get("column")
    c = r_ident(column) if column else ""
    expr = {
        "count": f"sum(!is.na({c}))" if column else "n()",
        "avg": f"mean({c}, na.rm = TRUE)",
        "sum": f"sum({c}, na.rm = TRUE)",
        "min": f"min({c}, na.rm = TRUE)",
        "max": f"max({c}, na.rm = TRUE)",
    }.get(func)
    if expr is None:  # the plan has already said why
        raise ExprError("Pick a summary: count, sum, avg, min or max.")
    return f"{r_ident(a.get('as') or '')} = {expr}"


def chunk_label(name: str) -> str:
    """A Quarto chunk label: letters, digits and dashes only."""
    return re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-") or "out"


class _RGen:
    def __init__(self, program: Program, tables: dict[str, TableInfo], quarto: bool,
                 title: str) -> None:
        self.program, self.tables, self.quarto, self.title = program, tables, quarto, title
        self.em = Emitter(indent="  ")
        self.diags: list[Diagnostic] = []
        self.expr = RRenderer()
        self.plans: dict[str, Plan] = {}
        self.fig = 0
        self.step = 0

    # ---- top level -------------------------------------------------------------------------

    def run(self) -> Generated:
        em = self.em
        blocks = self.program.blocks
        for b in self.program.walk():
            if b.type == "from":
                plan = build_plan(b, self.tables)
                self.plans[b.id] = plan
                self.diags += plan.diagnostics
        libs = ["dplyr", "readr"]
        if any(x.type == "text" for x in self.program.walk()):
            libs.append("stringr")
        plots = [x.id for x in self.program.walk() if x.type == "plot"]

        if self.quarto:
            em.emit("---")
            em.emit(f"title: {py_str(self.title)}")
            em.emit("format: html")
            em.emit("---")
            em.blank()
            em.emit("```{r}")
            em.emit("#| label: setup")
            em.emit("#| message: false")
        for lib in libs:
            em.emit(f"library({lib})")
        if plots:
            em.emit("library(ggplot2)", *plots)
        self.load_tables()
        if self.quarto:
            em.emit("```")
        em.blank()

        chunk: list[Block] = []
        for b in blocks:
            if b.type in ("from", "plot"):
                self.flush(chunk)
                chunk = []
                self.chunk([b])
            else:
                chunk.append(b)
        self.flush(chunk)
        return em.result("r", self.diags)

    def load_tables(self) -> None:
        loaded: set[str] = set()
        for b in self.program.walk():
            if b.type not in ("from", "join"):
                continue
            table = b.field("table")
            if not table or table in loaded:
                continue
            loaded.add(table)
            info = self.tables.get(table)
            path = info.file if info else f"data/{table}.csv"
            # keep the column types found at upload: readr would otherwise re-guess and read
            # text like "1,5", "14:30" or "2023-01-02" as a number, time or date, so the R
            # result would differ from SQL and pandas. "c" forces text; "?" lets readr guess.
            coltypes = ""
            if info:
                coltypes = "".join("c" if c.type == "text" else "?" for c in info.columns)
            spec = f", col_types = {py_str(coltypes)}" if coltypes and set(coltypes) != {"?"} else ""
            try:
                line = (f"{r_name(table, b.id)} <- read_csv({py_str(path)}, show_col_types = FALSE"
                        f"{spec})")
            except ExprError as exc:
                self.diags.append(error(str(exc), b.id, target="r"))
                continue
            self.em.emit(line, b.id)

    def flush(self, chunk: list[Block]) -> None:
        if chunk:
            self.chunk(chunk)

    def chunk(self, blocks: list[Block]) -> None:
        em = self.em
        first = blocks[0]
        if self.quarto:
            em.emit("```{r}")
            if first.type == "from":
                em.emit(f"#| label: {chunk_label(first.field('name') or 'out')}")
            elif first.type == "plot":
                self.fig += 1
                em.emit(f"#| label: fig-{self.fig}", first.id)
                em.emit(f"#| fig-cap: {py_str(_caption(first))}", first.id)
            else:
                self.step += 1
                em.emit(f"#| label: step-{self.step}")
        self.stmts(blocks)
        if first.type == "from" and em.depth == 0:
            em.emit(first.field("name") or "out")
        if self.quarto:
            em.emit("```")
        em.blank()

    # ---- statements --------------------------------------------------------------------------

    def stmts(self, blocks: list[Block]) -> None:
        for b in blocks:
            try:
                self.stmt(b)
            except ExprError as exc:
                self.diags.append(error(str(exc), exc.block_id or b.id, target="r"))
                self.em.emit(f"# {one_line(f'{b.type}: {exc}')}", b.id)

    def body(self, b: Block, name: str) -> None:
        self.em.depth += 1
        self.stmts(b.stack(name))
        self.em.depth -= 1

    def stmt(self, b: Block) -> None:
        em, t, e = self.em, b.type, self.expr
        if t == "from":
            self.pipeline(self.plans.get(b.id) or build_plan(b, self.tables))
        elif t == "setvar":
            em.emit(f"{r_name(b.field('name'), b.id)} <- {e(b.inputs.get('value'))}", b.id)
        elif t == "changevar":
            name = r_name(b.field("name"), b.id)
            em.emit(f"{name} <- {name} + {e(b.inputs.get('by'))}", b.id)
        elif t == "print":
            from blockcode.codegen.python import print_args

            args = [e(a) for a in print_args(b)]
            inner = args[0] if len(args) == 1 else f"paste({', '.join(args)})"
            em.emit(f"print({inner})", b.id)
        elif t == "foreach":
            over = b.inputs.get("over")
            var = r_name(b.field("var") or "row", b.id)
            if over is not None and over.type == "var":
                data = r_name(over.field("name"), b.id)
                em.emit(f"for (i in seq_len(nrow({data}))) {{", b.id)
                em.depth += 1
                em.emit(f"{var} <- {data}[i, ]", b.id)
                em.depth -= 1
            else:
                em.emit(f"for ({var} in {e(over)}) {{", b.id)
            self.body(b, "body")
            em.emit("}", b.id)
        elif t == "repeat":
            var = r_name(b.field("var") or "i", b.id)
            em.emit(f"for ({var} in seq_len({e(b.inputs.get('times'))}) - 1) {{", b.id)
            self.body(b, "body")
            em.emit("}", b.id)
        elif t == "if":
            em.emit(f"if ({e(b.inputs.get('cond'))}) {{", b.id)
            self.body(b, "body")
            if b.stack("else"):
                em.emit("} else {", b.id)
                self.body(b, "else")
            em.emit("}", b.id)
        elif t == "while":
            em.emit(f"while ({e(b.inputs.get('cond'))}) {{", b.id)
            self.body(b, "body")
            em.emit("}", b.id)
        elif t == "plot":
            self.plot(b)
        elif t == "raw":
            if b.field("lang") == "r":
                em.emit(b.field("code", "").rstrip("\n"), b.id)
            else:
                self.diags.append(error("This Python code can't run as R.", b.id, target="r"))
                for line in b.field("code", "").splitlines():
                    em.emit(f"# Python: {line}", b.id)
        else:
            raise ExprError(f'"{t}" can\'t be used as a step on its own.', b.id)

    def plot(self, b: Block) -> None:
        chart, data = b.field("chart", "bar"), r_name(b.field("data") or "out", b.id)
        x, y = b.field("x"), b.field("y")
        if not x:
            raise ExprError("Pick a column for the plot.", b.id)
        if chart == "hist":
            bins = whole(b.field("bins") or 5)
            if not bins:
                raise ExprError("The number of bins needs to be a whole number.", b.id)
            self.em.emit(f"ggplot({data}, aes(x = {r_ident(x)})) +", b.id)
            self.em.emit(f"  geom_histogram(bins = {bins})", b.id)
            return
        if chart not in GEOMS:
            raise ExprError("Pick a chart type: bar, line, scatter or hist.", b.id)
        if not y:
            raise ExprError("Pick a column for the y axis.", b.id)
        self.em.emit(f"ggplot({data}, aes(x = {r_ident(x)}, y = {r_ident(y)})) +", b.id)
        self.em.emit(f"  {GEOMS[chart]}", b.id)

    # ---- pipelines ---------------------------------------------------------------------------

    def pipeline(self, plan: Plan) -> None:
        e = self.expr
        verbs: list[tuple[str, str]] = []
        for j in plan.joins:
            fn = "left_join" if j.field("how") == "left" else "inner_join"
            right = r_name(j.field("table"), j.id)
            verbs.append((f"{fn}({right}, by = {py_str(str(j.field('on')))})", j.id))
        for d in plan.derives:
            verbs.append((f"mutate({r_ident(d.field('name'))} = {e(d.inputs.get('expr'))})", d.id))
        for w in plan.wheres:
            verbs.append((f"filter({e(w.inputs.get('cond'))})", w.id))
        if plan.group:
            g = plan.group
            by, aggs = g.field("by", []), g.field("aggs", [])
            if by and not aggs:
                verbs.append((f"distinct({', '.join(r_ident(k) for k in by)})", g.id))
            else:
                if by:
                    verbs.append((f"group_by({', '.join(r_ident(k) for k in by)})", g.id))
                parts = [_agg_r(a) for a in aggs]
                if len(by) > 1:
                    parts.append('.groups = "drop"')
                one = f"summarise({', '.join(parts)})"
                if len(one) <= 64:
                    verbs.append((one, g.id))
                else:
                    verbs.append(("summarise(\n  " + ",\n  ".join(parts) + "\n)", g.id))
        if plan.having:
            verbs.append((f"filter({e(plan.having.inputs.get('cond'))})", plan.having.id))
        if plan.select:
            cols = ", ".join(r_ident(c) for c in plan.select.field("columns", []))
            verbs.append((f"select({cols})", plan.select.id))
        if plan.order:
            keys = [f"desc({r_ident(k['column'])})" if k.get("desc") else r_ident(k["column"])
                    for k in plan.order.field("keys", [])]
            verbs.append((f"arrange({', '.join(keys)})", plan.order.id))
        # a LIMIT that isn't a whole number is reported by the plan and left out of the code
        if plan.limit and whole(plan.limit.field("n")) is not None:
            verbs.append((f"slice_head(n = {whole(plan.limit.field('n'))})", plan.limit.id))

        head = f"{r_name(plan.name, plan.block.id)} <- {r_name(plan.table, plan.block.id)}"
        if not verbs:
            self.em.emit(head, plan.block.id)
            return
        self.em.emit(head + " |>", plan.block.id)
        self.em.depth += 1
        for i, (text, bid) in enumerate(verbs):
            self.em.emit(text + (" |>" if i < len(verbs) - 1 else ""), bid)
        self.em.depth -= 1


def _caption(b: Block) -> str:
    chart, x, y = b.field("chart", "bar"), b.field("x"), b.field("y")
    if chart == "hist":
        return f"Histogram of {x}"
    return f"{chart.capitalize()} chart of {y} by {x}"
