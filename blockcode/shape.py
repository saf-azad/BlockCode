"""Check that a program is well formed before any code is written from it.

The editor always sends well-formed programs, but the API takes any JSON. Every field a code
generator reads is checked here for its type, so the generators can rely on it: a block whose
settings are the wrong kind of value is reported as a problem instead of reaching the code.
"""

from __future__ import annotations

from typing import Any, Callable

from blockcode.diagnostics import Diagnostic, error
from blockcode.ir import Block, Program
from blockcode.registry import SPECS

MAX_BLOCKS = 2000
MAX_DEPTH = 150

Check = Callable[[Any], bool]


def _opt(check: Check) -> Check:
    return lambda v: v is None or check(v)


def _str(v: Any) -> bool:
    return isinstance(v, str)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _list_of(check: Check) -> Check:
    return lambda v: isinstance(v, list) and all(check(x) for x in v)


def _agg(v: Any) -> bool:
    return (isinstance(v, dict) and _str(v.get("func")) and _opt(_str)(v.get("column"))
            and _opt(_str)(v.get("as")))


def _key(v: Any) -> bool:
    return isinstance(v, dict) and _str(v.get("column")) and _opt(lambda d: isinstance(d, bool))(
        v.get("desc"))


S, OS = _str, _opt(_str)
FIELDS: dict[str, dict[str, Check]] = {
    "from": {"table": OS, "name": OS},
    "join": {"table": OS, "on": OS, "how": OS},
    "derive": {"name": OS},
    "group": {"by": _opt(_list_of(S)), "aggs": _opt(_list_of(_agg))},
    "select": {"columns": _opt(_list_of(S))},
    "order": {"keys": _opt(_list_of(_key))},
    "limit": {"n": _scalar},  # a bad count is the plan's to explain
    "col": {"name": OS},
    "lit": {"value": _scalar},
    "cmp": {"op": OS},
    "logic": {"op": OS},
    "math": {"op": OS},
    "inlist": {"values": _opt(_list_of(_scalar))},
    "text": {"op": OS, "value": _scalar},
    "var": {"name": OS},
    "field": {"var": OS, "name": OS},
    "setvar": {"name": OS},
    "changevar": {"name": OS},
    "foreach": {"var": OS},
    "repeat": {"var": OS},
    "plot": {"chart": OS, "data": OS, "x": OS, "y": OS, "bins": _opt(_num)},
    "raw": {"code": OS, "lang": OS},
}


def shape_problems(program: Program) -> list[Diagnostic]:
    """Problems that stop any code being written: unknown blocks, settings of the wrong kind,
    or a program too big or too deeply nested to be one a learner built."""
    diags: list[Diagnostic] = []
    count = 0

    def visit(b: Block, depth: int) -> None:
        nonlocal count
        count += 1
        if depth > MAX_DEPTH:
            diags.append(error("These blocks are nested too deeply.", b.id))
            return
        if b.type not in SPECS:
            diags.append(error("This block isn't one BlockCode knows.", b.id))
            return
        for name, check in FIELDS.get(b.type, {}).items():
            if not check(b.fields.get(name)):
                diags.append(error(f"This block's {name} setting isn't valid. Remove the block "
                                   f"and add it again.", b.id))
        for child in b.inputs.values():
            visit(child, depth + 1)
        for stack in b.stacks.values():
            for child in stack:
                visit(child, depth + 1)

    for top in program.blocks:
        visit(top, 0)
        if count > MAX_BLOCKS:
            return [error(f"This program has more than {MAX_BLOCKS} blocks, which is too many "
                          f"to work with.")]
    return diags
