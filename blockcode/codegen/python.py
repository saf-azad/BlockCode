"""Program → Python. Data stacks become pandas pipelines; loops, ifs and prints wrap them."""

from __future__ import annotations

from blockcode.codegen.emitter import Emitter, Generated
from blockcode.codegen.expr import ExprError, PyRenderer, py_str
from blockcode.codegen.pandas import emit_pipeline
from blockcode.diagnostics import Diagnostic, error
from blockcode.ir import Block, Program, TableInfo
from blockcode.plan import build_plan

PLOT_KINDS = ("bar", "line", "scatter", "hist")


def generate_python(program: Program, tables: dict[str, TableInfo]) -> Generated:
    gen = _PyGen(tables)
    em = gen.em
    em.emit("import pandas as pd")
    plots = [b.id for b in program.walk() if b.type == "plot"]
    if plots:
        em.emit("import matplotlib.pyplot as plt", *plots)
    em.blank()
    gen.stmts(program.blocks)
    return em.result("python", gen.diags)


class _PyGen:
    def __init__(self, tables: dict[str, TableInfo]) -> None:
        self.tables = tables
        self.em = Emitter()
        self.diags: list[Diagnostic] = []
        self.loaded: set[str] = set()
        self.expr = PyRenderer()

    def e(self, block: Block, slot: str) -> str:
        return self.expr(block.inputs.get(slot))

    def stmts(self, blocks: list[Block]) -> None:
        if not blocks:
            self.em.emit("pass")
            return
        for b in blocks:
            try:
                self.stmt(b)
            except ExprError as exc:
                self.diags.append(error(str(exc), exc.block_id or b.id, target="python"))
                self.em.emit(f"...  # {b.type}: {exc}", b.id)

    def stmt(self, b: Block) -> None:
        em = self.em
        t = b.type
        if t == "from":
            plan = build_plan(b, self.tables)
            self.diags += plan.diagnostics
            if em.depth == 0:
                em.blank()
            emit_pipeline(em, plan, self.tables, self.loaded)
            if em.depth == 0:
                em.blank()
        elif t == "setvar":
            em.emit(f"{b.field('name')} = {self.e(b, 'value')}", b.id)
        elif t == "changevar":
            em.emit(f"{b.field('name')} += {self.e(b, 'by')}", b.id)
        elif t == "print":
            args = ", ".join(self.expr(v) for v in print_args(b))
            em.emit(f"print({args})", b.id)
        elif t == "foreach":
            over = b.inputs.get("over")
            var = b.field("var") or "row"
            if over is not None and over.type == "var":
                em.emit(f"for {var} in {over.field('name')}.itertuples(index=False):", b.id)
            else:
                em.emit(f"for {var} in {self.e(b, 'over')}:", b.id)
            self.body(b, "body")
        elif t == "repeat":
            em.emit(f"for {b.field('var') or 'i'} in range({self.e(b, 'times')}):", b.id)
            self.body(b, "body")
        elif t == "if":
            em.emit(f"if {self.e(b, 'cond')}:", b.id)
            self.body(b, "body")
            if b.stack("else"):
                em.emit("else:", b.id)
                self.body(b, "else")
        elif t == "while":
            em.emit(f"while {self.e(b, 'cond')}:", b.id)
            self.body(b, "body")
        elif t == "plot":
            self.plot(b)
        elif t == "raw":
            if b.field("lang", "python") == "python":
                em.emit(b.field("code", "").rstrip("\n"), b.id)
            else:
                self.diags.append(error("This R code can't run as Python.", b.id,
                                        target="python"))
                for line in b.field("code", "").splitlines():
                    em.emit(f"# R: {line}", b.id)
        else:
            raise ExprError(f'"{t}" can\'t be used as a step on its own.', b.id)

    def body(self, b: Block, name: str) -> None:
        self.em.depth += 1
        self.stmts(b.stack(name))
        self.em.depth -= 1

    def plot(self, b: Block) -> None:
        em = self.em
        chart, data = b.field("chart", "bar"), b.field("data") or "out"
        x, y = b.field("x"), b.field("y")
        if chart not in PLOT_KINDS:
            raise ExprError(f'"{chart}" is not a chart type.', b.id)
        if not x:
            raise ExprError("Pick a column for the plot.", b.id)
        if chart == "hist":
            em.emit(f"{data}[{py_str(x)}].plot.hist(bins={int(b.field('bins') or 5)})", b.id)
        else:
            if not y:
                raise ExprError("Pick a column for the y axis.", b.id)
            em.emit(f"{data}.plot.{chart}(x={py_str(x)}, y={py_str(y)})", b.id)
        em.emit("plt.show()", b.id)


def print_args(b: Block) -> list[Block]:
    """Print's inputs are arg0, arg1, ... in order."""
    return [v for k, v in sorted(b.inputs.items(), key=lambda kv: int(kv[0][3:] or 0))]
