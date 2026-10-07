"""Small helpers for building programs in Python: used by parsers, examples and tests.

    from blockcode import build as b
    prog = b.program(
        b.from_("enrolments",
            b.join("courses", "course_id"),
            b.where(b.cmp(">", b.col("grade"), b.lit(50))),
            b.group(["dept"], b.agg("avg", "grade", "avg_grade"), b.agg("count", None, "n")),
            b.order(("avg_grade", True)),
            b.limit(5),
        )
    )
"""

from __future__ import annotations

from typing import Any

from blockcode.ir import Block, Program, new_id


def block(type: str, fields: dict | None = None, inputs: dict | None = None,
          stacks: dict | None = None, id: str | None = None) -> Block:
    return Block(id=id or new_id(), type=type, fields=fields or {}, inputs=inputs or {},
                 stacks=stacks or {})


def program(*blocks: Block) -> Program:
    return Program(blocks=list(blocks))


# ---- data blocks -------------------------------------------------------------------------

def from_(table: str, *steps: Block, name: str = "out") -> Block:
    return block("from", {"table": table, "name": name}, stacks={"steps": list(steps)})


def join(table: str, on: str, how: str = "inner") -> Block:
    return block("join", {"table": table, "on": on, "how": how})


def where(cond: Block) -> Block:
    return block("where", inputs={"cond": cond})


def derive(name: str, expr: Block) -> Block:
    return block("derive", {"name": name}, inputs={"expr": expr})


def agg(func: str, column: str | None, as_: str) -> dict:
    return {"func": func, "column": column, "as": as_}


def group(by: list[str], *aggs: dict) -> Block:
    return block("group", {"by": list(by), "aggs": list(aggs)})


def having(cond: Block) -> Block:
    return block("having", inputs={"cond": cond})


def select(*columns: str) -> Block:
    return block("select", {"columns": list(columns)})


def order(*keys: tuple[str, bool] | str) -> Block:
    out = []
    for k in keys:
        col, desc = (k, False) if isinstance(k, str) else k
        out.append({"column": col, "desc": desc})
    return block("order", {"keys": out})


def limit(n: int) -> Block:
    return block("limit", {"n": n})


# ---- expressions --------------------------------------------------------------------------

def col(name: str) -> Block:
    return block("col", {"name": name})


def lit(value: Any) -> Block:
    return block("lit", {"value": value})


def var(name: str) -> Block:
    return block("var", {"name": name})


def field(var_name: str, name: str) -> Block:
    return block("field", {"var": var_name, "name": name})


def cmp(op: str, a: Block, b: Block) -> Block:
    return block("cmp", {"op": op}, {"a": a, "b": b})


def and_(a: Block, b: Block) -> Block:
    return block("logic", {"op": "and"}, {"a": a, "b": b})


def or_(a: Block, b: Block) -> Block:
    return block("logic", {"op": "or"}, {"a": a, "b": b})


def not_(a: Block) -> Block:
    return block("not", inputs={"a": a})


def math(op: str, a: Block, b: Block) -> Block:
    return block("math", {"op": op}, {"a": a, "b": b})


def isempty(a: Block) -> Block:
    return block("isempty", inputs={"a": a})


def inlist(a: Block, values: list) -> Block:
    return block("inlist", {"values": list(values)}, {"a": a})


def text(op: str, a: Block, value: str) -> Block:
    return block("text", {"op": op, "value": value}, {"a": a})


# ---- Python / R only blocks ---------------------------------------------------------------

def setvar(name: str, value: Block) -> Block:
    return block("setvar", {"name": name}, {"value": value})


def changevar(name: str, by: Block) -> Block:
    return block("changevar", {"name": name}, {"by": by})


def print_(*args: Block) -> Block:
    return block("print", inputs={f"arg{i}": a for i, a in enumerate(args)})


def foreach(var_name: str, over: Block, *body: Block) -> Block:
    return block("foreach", {"var": var_name}, {"over": over}, {"body": list(body)})


def repeat(var_name: str, times: Block, *body: Block) -> Block:
    return block("repeat", {"var": var_name}, {"times": times}, {"body": list(body)})


def if_(cond: Block, body: list[Block], orelse: list[Block] | None = None) -> Block:
    stacks = {"body": list(body)}
    if orelse:
        stacks["else"] = list(orelse)
    return block("if", inputs={"cond": cond}, stacks=stacks)


def while_(cond: Block, *body: Block) -> Block:
    return block("while", inputs={"cond": cond}, stacks={"body": list(body)})


def plot(chart: str, data: str, x: str, y: str | None = None) -> Block:
    return block("plot", {"chart": chart, "data": data, "x": x, "y": y})


def raw(lang: str, code: str) -> Block:
    return block("raw", {"lang": lang, "code": code})
