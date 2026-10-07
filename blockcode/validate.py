"""Per-target checks: everything the code generators report, plus variable use before set."""

from __future__ import annotations

from blockcode.codegen import generate
from blockcode.diagnostics import Diagnostic, error, warning
from blockcode.ir import Block, Program, TableInfo


def validate(program: Program, tables: dict[str, TableInfo], target: str) -> list[Diagnostic]:
    diags = list(generate(program, tables, target).diagnostics)
    if target != "sql":
        diags += check_variables(program)
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
