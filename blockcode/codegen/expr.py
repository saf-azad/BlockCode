"""Expression renderers for each target, with precedence-aware parentheses.

Each renderer returns ``(text, precedence)``; a higher precedence binds tighter. Operands are
wrapped in parentheses only when they bind more loosely than their parent needs.
"""

from __future__ import annotations

import keyword
import re
from typing import Callable

from blockcode.ir import Block

ATOM = 99

CMP_OPS = ("=", "!=", "<", "<=", ">", ">=")
MATH_OPS = ("+", "-", "*", "/", "%")


class ExprError(ValueError):
    def __init__(self, message: str, block_id: str | None = None) -> None:
        super().__init__(message)
        self.block_id = block_id


def _escape_char(ch: str) -> str:
    if ch == "\n":
        return "\\n"
    if ch == "\t":
        return "\\t"
    # every other control character, and the Unicode line breaks, as a \u escape that
    # Python, R and YAML all read back the same, so a string never spans lines
    if ord(ch) < 32 or ord(ch) == 127 or ch in "\u0085  ":
        return f"\\u{ord(ch):04x}"
    return ch


_NEEDS_ESCAPE = re.compile(r"[\x00-\x1f\x7f\u0085  ]")


def py_str(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + _NEEDS_ESCAPE.sub(lambda m: _escape_char(m.group()), s) + '"'


def one_line(text: str) -> str:
    """Text for a code comment: always a single line."""
    return " ".join(str(text).split())


_PY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PY_TAKEN = {"pd", "plt", "np"}  # the generated Python already uses these


def name_problem(name) -> str | None:
    """Why ``name`` can't be a variable in the generated Python, or None if it can.

    Table, result, Set var and loop names are written into the code as they are, so they
    must be plain identifiers."""
    if isinstance(name, str) and _PY_NAME.match(name) and not keyword.iskeyword(name) \
            and name not in PY_TAKEN:
        return None
    shown = one_line(str(name))[:40]
    return (f'"{shown}" can\'t be a name in Python. Pick another one that starts with a letter '
            f"and isn't a Python word like for or class.")


def checked_name(name, block_id: str | None = None) -> str:
    problem = name_problem(name)
    if problem:
        raise ExprError(problem, block_id)
    return name


def whole(value) -> int | None:
    """A count written into the code (LIMIT, bins) as a plain int, or None if it isn't one."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def py_lit(v) -> str:
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return repr(v)
    return py_str(str(v))


def py_kwarg(name: str, value: str) -> str:
    """``name=value`` in a call, or ``**{"name": value}`` when name isn't a Python identifier
    (a column called "for" or "2nd")."""
    if name.isidentifier() and not keyword.iskeyword(name):
        return f"{name}={value}"
    return f"**{{{py_str(name)}: {value}}}"


def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def sql_lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return sql_str(str(v))


def r_lit(v) -> str:
    if v is None:
        return "NA"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return py_str(str(v))


_SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Words SQLite (or the sqlglot parser) can't take as a bare column or table name, found by
# trying each SQLite keyword in SELECT / WHERE / GROUP BY / ORDER BY / USING.
_SQL_RESERVED = set("""
add all alter and as autoincrement between case cast check collate commit constraint create
cross current_date current_time current_timestamp default deferrable delete distinct drop else
escape except exists for foreign from glob group having if in index inner insert intersect into
is isnull join like limit not nothing notnull null offset on or order outer primary raise
references regexp returning rollback select set table then to transaction union unique update
using values when where window with
""".split())


def sql_ident(name: str) -> str:
    if _SQL_IDENT.match(name) and name.lower() not in _SQL_RESERVED:
        return name
    return '"' + name.replace('"', '""') + '"'


_R_IDENT = re.compile(r"^[A-Za-z.][A-Za-z0-9._]*$")
_R_RESERVED = {"if", "else", "repeat", "while", "function", "for", "next", "break", "TRUE",
               "FALSE", "NULL", "Inf", "NaN", "NA", "in"}


def r_ident(name: str) -> str:
    if _R_IDENT.match(name) and name not in _R_RESERVED and not re.match(r"^\.\d", name):
        return name
    return "`" + name.replace("`", "\\`") + "`"


def _wrap(part: tuple[str, int], need: int) -> str:
    text, prec = part
    return text if prec >= need else f"({text})"


class Renderer:
    """Base renderer: subclasses set the operator tables and override the leaf cases."""

    prec = {"or": 1, "and": 2, "not": 3, "cmp": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}
    ops = {"=": "=", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
    words = {"and": "AND", "or": "OR"}
    math_ops = {"+": "+", "-": "-", "*": "*", "/": "/", "%": "%"}

    def __call__(self, e: Block | None) -> str:
        return self.render(e)[0]

    def render(self, e: Block | None) -> tuple[str, int]:
        if e is None:
            raise ExprError("An empty slot needs a value.")
        fn: Callable | None = getattr(self, "r_" + e.type, None)
        if fn is None:
            raise ExprError(f'"{e.type}" can\'t be used here.', e.id)
        return fn(e)

    def sub(self, e: Block, slot: str) -> tuple[str, int]:
        child = e.inputs.get(slot)
        if child is None:
            raise ExprError("This block has an empty slot.", e.id)
        return self.render(child)

    def r_cmp(self, e: Block) -> tuple[str, int]:
        p = self.prec["cmp"]
        op = e.field("op")
        if op not in self.ops:
            raise ExprError(f'"{op}" is not a comparison.', e.id)
        a, b = self.sub(e, "a"), self.sub(e, "b")
        return f"{_wrap(a, p + 1)} {self.ops[op]} {_wrap(b, p + 1)}", p

    def logic_op(self, e: Block) -> str:
        op = e.field("op")
        if op not in self.words:
            raise ExprError('Pick "and" or "or".', e.id)
        return op

    def r_logic(self, e: Block) -> tuple[str, int]:
        op = self.logic_op(e)
        p = self.prec[op]
        a, b = self.sub(e, "a"), self.sub(e, "b")
        return f"{_wrap(a, p)} {self.words[op]} {_wrap(b, p)}", p

    def r_math(self, e: Block) -> tuple[str, int]:
        op = e.field("op")
        if op not in self.math_ops:
            raise ExprError(f'"{op}" is not a maths operator.', e.id)
        p = self.prec[op]
        a, b = self.sub(e, "a"), self.sub(e, "b")
        return f"{_wrap(a, p)} {self.math_ops[op]} {_wrap(b, p + 1)}", p


class SqlRenderer(Renderer):
    """SQLite. ``resolve`` lets the SQL generator inline derived columns and aggregates."""

    def __init__(self, resolve: Callable[[str], tuple[str, int] | None] | None = None,
                 types: dict[str, str] | None = None) -> None:
        self.resolve = resolve
        self.types = types or {}

    def r_col(self, e):
        name = e.field("name")
        if self.resolve:
            got = self.resolve(name)
            if got:
                return got
        return sql_ident(name), ATOM

    def r_lit(self, e):
        return sql_lit(e.field("value")), ATOM

    def r_not(self, e):
        return f"NOT {_wrap(self.sub(e, 'a'), ATOM)}", self.prec["not"]

    def r_isempty(self, e):
        return f"{_wrap(self.sub(e, 'a'), 5)} IS NULL", self.prec["cmp"]

    def r_inlist(self, e):
        vals = ", ".join(sql_lit(v) for v in e.field("values", []))
        return f"{_wrap(self.sub(e, 'a'), 5)} IN ({vals})", self.prec["cmp"]

    def r_text(self, e):
        v = str(e.field("value", ""))
        pat = {"contains": f"%{v}%", "starts": f"{v}%", "ends": f"%{v}"}.get(e.field("op"))
        if pat is None:
            raise ExprError(f'"{e.field("op")}" is not a text test.', e.id)
        return f"{_wrap(self.sub(e, 'a'), 5)} LIKE {sql_str(pat)}", self.prec["cmp"]

    def _is_int(self, e: Block | None) -> bool:
        if e is None:
            return False
        if e.type == "lit":
            v = e.field("value")
            return isinstance(v, int) and not isinstance(v, bool)
        if e.type == "col":
            return self.types.get(e.field("name")) == "int"
        if e.type == "math" and e.field("op") in ("+", "-", "*", "%"):
            return self._is_int(e.inputs.get("a")) and self._is_int(e.inputs.get("b"))
        return False

    def r_math(self, e):
        # SQLite divides whole numbers as whole numbers (7 / 2 = 3). pandas and R give 3.5, so
        # make the division a decimal one when both sides are whole numbers.
        if e.field("op") == "/":
            a, b = e.inputs.get("a"), e.inputs.get("b")
            if self._is_int(a) and self._is_int(b):
                p = self.prec["/"]
                if b is not None and b.type == "lit":
                    return f"{_wrap(self.sub(e, 'a'), p)} / {float(b.field('value'))!r}", p
                return f"CAST({self.sub(e, 'a')[0]} AS REAL) / {_wrap(self.sub(e, 'b'), p + 1)}", p
        return super().r_math(e)


class PandasRenderer(Renderer):
    """pandas boolean masks and column maths over a data frame variable."""

    prec = {"or": 3, "and": 4, "not": 8, "cmp": 2, "+": 6, "-": 6, "*": 7, "/": 7, "%": 7}
    ops = {"=": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
    words = {"and": "&", "or": "|"}

    def __init__(self, frame: str) -> None:
        self.frame = frame

    def r_col(self, e):
        return f"{self.frame}[{py_str(e.field('name'))}]", ATOM

    def r_lit(self, e):
        return py_lit(e.field("value")), ATOM

    def r_logic(self, e):
        # & and | bind tighter than comparisons in Python, so comparisons always get brackets.
        op = self.logic_op(e)
        p = self.prec[op]
        a, b = self.sub(e, "a"), self.sub(e, "b")
        return f"{_wrap(a, p)} {self.words[op]} {_wrap(b, p)}", p

    def r_not(self, e):
        return f"~{_wrap(self.sub(e, 'a'), ATOM)}", self.prec["not"]

    def r_isempty(self, e):
        return f"{_wrap(self.sub(e, 'a'), ATOM)}.isna()", ATOM

    def r_inlist(self, e):
        vals = ", ".join(py_lit(v) for v in e.field("values", []))
        return f"{_wrap(self.sub(e, 'a'), ATOM)}.isin([{vals}])", ATOM

    def r_text(self, e):
        v = py_str(str(e.field("value", "")).lower())
        a = _wrap(self.sub(e, "a"), ATOM)
        call = {"contains": f".str.contains({v}, regex=False)", "starts": f".str.startswith({v})",
                "ends": f".str.endswith({v})"}.get(e.field("op"))
        if call is None:
            raise ExprError(f'"{e.field("op")}" is not a text test.', e.id)
        return f"{a}.str.lower(){call}", ATOM


class RRenderer(Renderer):
    """dplyr verbs: bare column names, vectorised & | !."""

    prec = {"or": 1, "and": 2, "not": 3, "cmp": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}
    ops = {"=": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
    words = {"and": "&", "or": "|"}
    math_ops = {"+": "+", "-": "-", "*": "*", "/": "/", "%": "%%"}

    def r_col(self, e):
        return r_ident(e.field("name")), ATOM

    def r_lit(self, e):
        return r_lit(e.field("value")), ATOM

    def r_var(self, e):
        return r_ident(e.field("name")), ATOM

    def r_field(self, e):
        return f"{r_ident(e.field('var'))}${r_ident(e.field('name'))}", ATOM

    def r_not(self, e):
        return f"!{_wrap(self.sub(e, 'a'), ATOM)}", self.prec["not"]

    def r_isempty(self, e):
        return f"is.na({self.sub(e, 'a')[0]})", ATOM

    def r_inlist(self, e):
        vals = ", ".join(r_lit(v) for v in e.field("values", []))
        return f"{_wrap(self.sub(e, 'a'), 7)} %in% c({vals})", 7

    def r_text(self, e):
        v = r_lit(str(e.field("value", "")).lower())
        fn = {"contains": "str_detect", "starts": "str_starts", "ends": "str_ends"}.get(
            e.field("op"))
        if fn is None:
            raise ExprError(f'"{e.field("op")}" is not a text test.', e.id)
        return f"{fn}(tolower({self.sub(e, 'a')[0]}), fixed({v}))", ATOM


class PyRenderer(Renderer):
    """Plain Python values inside loops and ifs (not pandas columns)."""

    prec = {"or": 1, "and": 2, "not": 3, "cmp": 4, "+": 6, "-": 6, "*": 7, "/": 7, "%": 7}
    ops = {"=": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
    words = {"and": "and", "or": "or"}

    def r_lit(self, e):
        return py_lit(e.field("value")), ATOM

    def r_var(self, e):
        return checked_name(e.field("name"), e.id), ATOM

    def r_field(self, e):
        name = e.field("name")
        if not isinstance(name, str) or not name.isidentifier() or keyword.iskeyword(name):
            raise ExprError(f'"{one_line(str(name))[:40]}" can\'t be read as a row field in '
                            f"Python. Rename the column so it starts with a letter and has no "
                            f"spaces.", e.id)
        return f"{checked_name(e.field('var'), e.id)}.{name}", ATOM

    def r_col(self, e):
        raise ExprError(f'Use a row field like row.{one_line(str(e.field("name")))[:40]} here, '
                        f"not a column.", e.id)

    def r_not(self, e):
        return f"not {_wrap(self.sub(e, 'a'), self.prec['not'])}", self.prec["not"]

    def r_isempty(self, e):
        return f"pd.isna({self.sub(e, 'a')[0]})", ATOM

    def r_inlist(self, e):
        vals = ", ".join(py_lit(v) for v in e.field("values", []))
        return f"{_wrap(self.sub(e, 'a'), 5)} in [{vals}]", self.prec["cmp"]

    def r_text(self, e):
        v = py_str(str(e.field("value", "")).lower())
        a = _wrap(self.sub(e, "a"), ATOM)
        op = e.field("op")
        if op == "contains":
            return f"{v} in str({a}).lower()", self.prec["cmp"]
        if op in ("starts", "ends"):
            return f"str({a}).lower().{op}with({v})", ATOM
        raise ExprError(f'"{op}" is not a text test.', e.id)
