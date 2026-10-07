"""Python (pandas) → blocks with the standard ``ast`` module.

Recognises the pandas BlockCode writes (one reassignment per step) and the usual hand-written
variants: method chains, ``.query()``, ``.loc[...]``, ``pd.merge``, ``df.col`` attributes,
``.notna()``, ``.between()``. Statements it can't show as blocks become a raw Code block.
"""

from __future__ import annotations

import ast

from blockcode import build as b
from blockcode.diagnostics import Diagnostic, error
from blockcode.ir import Block, Program, TableInfo
from blockcode.parse import ParseResult, Spans, Unsupported, table_for_path

CMP = {ast.Eq: "=", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
MATH = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Mod: "%"}
AGG = {"mean": "avg", "sum": "sum", "min": "min", "max": "max", "count": "count",
       "size": "count", "average": "avg"}
SKIP_IMPORTS = {"pandas", "matplotlib", "matplotlib.pyplot", "numpy"}
PLOT_KINDS = {"bar", "line", "scatter", "hist"}


def parse_python(code: str, tables: dict[str, TableInfo], previous: Program | None
                 ) -> ParseResult:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ParseResult(ok=False, lang="python", diagnostics=[
            error(f"The Python has a typo: {exc.msg}", line=exc.lineno, target="python")])
    p = _PyParser(code, tables)
    blocks = p.stmts(tree.body)
    return ParseResult(ok=True, lang="python", program=Program(blocks=blocks),
                       spans=p.spans.map, diagnostics=p.diags)


def _lines(node: ast.AST) -> range:
    return range(node.lineno, (node.end_lineno or node.lineno) + 1)


def _const(node: ast.AST, *types):
    if isinstance(node, ast.Constant) and isinstance(node.value, types or (object,)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and \
            isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)) \
            and not isinstance(node.operand.value, bool):
        return -node.operand.value
    raise Unsupported("expected a value here", getattr(node, "lineno", None))


def _strs(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_const(e, str) for e in node.elts]
    raise Unsupported("expected column names here", getattr(node, "lineno", None))


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


class _PyParser:
    def __init__(self, code: str, tables: dict[str, TableInfo]) -> None:
        self.code = code
        self.tables = tables
        self.spans = Spans()
        self.diags: list[Diagnostic] = []
        self.table_vars: dict[str, tuple[str, list[int]]] = {}
        self.pipes: dict[str, Block] = {}
        self.last_plot: Block | None = None

    # ---- statements --------------------------------------------------------------------------

    def stmts(self, nodes: list[ast.stmt]) -> list[Block]:
        out: list[Block] = []
        for node in nodes:
            try:
                made = self.stmt(node, out)
            except Unsupported:
                made = None
                self.raw(node, out)
            if made is not None:
                out.append(made)
        return out

    def raw(self, node: ast.stmt, out: list[Block]) -> None:
        text = ast.get_source_segment(self.code, node, padded=False) or ""
        lines = list(_lines(node))
        prev = out[-1] if out else None
        if prev is not None and prev.type == "raw" and \
                max(self.spans.map.get(prev.id, [0])) == node.lineno - 1:
            prev.fields["code"] += "\n" + text
            self.spans.add(prev, *lines)
        else:
            out.append(self.spans.add(b.raw("python", text), *lines))
        self.diags.append(Diagnostic(severity="info", line=node.lineno, target="python",
                                     message="This line can't become a block yet, so it stays "
                                             "as code."))

    def stmt(self, node: ast.stmt, out: list[Block]) -> Block | None:
        lines = list(_lines(node))
        if isinstance(node, ast.Import):
            if all(a.name in SKIP_IMPORTS for a in node.names):
                return None
            raise Unsupported("import")
        if isinstance(node, ast.ImportFrom):
            raise Unsupported("import")
        if isinstance(node, ast.Pass):
            return None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            return self.assign(node.targets[0].id, node.value, lines)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and \
                isinstance(node.op, ast.Add):
            return self.spans.add(b.changevar(node.target.id, self.iexpr(node.value)), *lines)
        if isinstance(node, ast.Expr):
            return self.expr_stmt(node.value, lines)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and not node.orelse:
            return self.for_(node, lines)
        if isinstance(node, ast.If):
            blk = b.if_(self.iexpr(node.test), [])
            self.spans.add(blk, node.lineno)
            blk.stacks["body"] = self.stmts(node.body)
            if node.orelse:
                blk.stacks["else"] = self.stmts(node.orelse)
                if not (len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)):
                    self.spans.add(blk, node.orelse[0].lineno - 1)
            return blk
        if isinstance(node, ast.While) and not node.orelse:
            blk = b.while_(self.iexpr(node.test))
            self.spans.add(blk, node.lineno)
            blk.stacks["body"] = self.stmts(node.body)
            return blk
        raise Unsupported("statement")

    def for_(self, node: ast.For, lines: list[int]) -> Block:
        it, var = node.iter, node.target.id
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and \
                it.func.attr == "itertuples" and isinstance(it.func.value, ast.Name):
            blk = b.foreach(var, b.var(it.func.value.id))
        elif isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and \
                it.func.id == "range" and len(it.args) in (1, 2) and not it.keywords:
            if len(it.args) == 2 and _const(it.args[0], int) != 0:
                raise Unsupported("range with a start")
            blk = b.repeat(var, self.iexpr(it.args[-1]))
        else:
            raise Unsupported("for loop")
        self.spans.add(blk, node.lineno)
        blk.stacks["body"] = self.stmts(node.body)
        return blk

    def assign(self, target: str, value: ast.expr, lines: list[int]) -> Block | None:
        # enrolments = pd.read_csv("data/enrolments.csv")
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and \
                value.func.attr == "read_csv" and value.args:
            path = _const(value.args[0], str)
            self.table_vars[target] = (table_for_path(path, self.tables), lines)
            return None
        chain = self.chain(value)
        if chain is not None:
            base, steps = chain
            if base not in self.pipes:
                table, tlines = self.table_vars[base]
                frm = b.from_(table, name=target)
                self.spans.add(frm, *tlines, *lines)
                self.pipes[target] = frm
                self.extend(frm, steps, lines)
                return frm
            frm = self.pipes[base]
            self.extend(frm, steps, lines)
            if target != base:
                frm.fields["name"] = target
                self.pipes[target] = frm
            if not steps:
                self.spans.add(frm, *lines)
            return None
        return self.spans.add(b.setvar(target, self.iexpr(value)), *lines)

    def extend(self, frm: Block, steps: list[Block], lines: list[int]) -> None:
        existing = frm.stacks.setdefault("steps", [])
        for s in steps:
            self.spans.add(s, *lines)
            if s.type == "join":
                tv = s.fields.pop("_var", None)
                if tv in self.table_vars:
                    self.spans.add(s, *self.table_vars[tv][1])
            grouped = any(x.type == "group" for x in existing)
            if s.type == "where" and grouped:
                s = b.having(s.inputs["cond"])
                self.spans.add(s, *lines)
                old = next((x for x in existing if x.type == "having"), None)
                if old is not None:
                    old.inputs["cond"] = b.and_(old.inputs["cond"], s.inputs["cond"])
                    self.spans.add(old, *lines)
                    continue
            existing.append(s)

    def expr_stmt(self, value: ast.expr, lines: list[int]) -> Block | None:
        if isinstance(value, ast.Name) and value.id in self.pipes:
            self.spans.add(self.pipes[value.id], *lines)
            return None
        if not isinstance(value, ast.Call):
            raise Unsupported("expression")
        f = value.func
        if isinstance(f, ast.Name) and f.id == "print" and not value.keywords:
            return self.spans.add(b.print_(*[self.iexpr(a) for a in value.args]), *lines)
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and \
                f.value.id == "plt" and f.attr == "show" and self.last_plot is not None:
            self.spans.add(self.last_plot, *lines)
            self.last_plot = None
            return None
        plot = self.plot(value)
        if plot is not None:
            self.last_plot = plot
            return self.spans.add(plot, *lines)
        raise Unsupported("call")

    def plot(self, call: ast.Call) -> Block | None:
        f = call.func
        if not isinstance(f, ast.Attribute):
            return None
        # out.plot.bar(x=..., y=...) / out["c"].plot.hist(bins=5)
        if isinstance(f.value, ast.Attribute) and f.value.attr == "plot":
            kind, recv = f.attr, f.value.value
        elif f.attr == "plot":
            kind_node = _kw(call, "kind")
            kind, recv = (_const(kind_node, str) if kind_node else "line"), f.value
        else:
            return None
        if kind not in PLOT_KINDS:
            raise Unsupported(f"{kind} plot")
        if kind == "hist":
            if isinstance(recv, ast.Subscript) and isinstance(recv.value, ast.Name):
                col = _const(recv.slice, str)
                bins = _kw(call, "bins")
                blk = b.plot("hist", recv.value.id, col)
                blk.fields["bins"] = _const(bins, int) if bins else 10
                return blk
            raise Unsupported("hist plot")
        if not isinstance(recv, ast.Name):
            raise Unsupported("plot")
        x, y = _kw(call, "x"), _kw(call, "y")
        if x is None or y is None:
            raise Unsupported("plot needs x and y")
        return b.plot(kind, recv.id, _const(x, str), _const(y, str))

    # ---- pandas chains ------------------------------------------------------------------------

    def is_frame(self, name: str) -> bool:
        return name in self.pipes or name in self.table_vars

    def chain(self, node: ast.expr) -> tuple[str, list[Block]] | None:
        """(base variable, steps) for a frame expression, or None if it isn't one."""
        if isinstance(node, ast.Name):
            return (node.id, []) if self.is_frame(node.id) else None
        # pd.merge(a, b, on=...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                isinstance(node.func.value, ast.Name) and node.func.value.id == "pd":
            if node.func.attr == "merge" and len(node.args) == 2:
                inner = self.chain(node.args[0])
                if inner is None:
                    return None
                return inner[0], inner[1] + [self.join(node, node.args[1])]
            if node.func.attr == "DataFrame" and node.args and isinstance(node.args[0], ast.Dict):
                return self.whole_table(node.args[0])
            return None
        if isinstance(node, ast.Subscript):
            target = node.value
            if isinstance(target, ast.Attribute) and target.attr == "loc":
                target = target.value
            inner = self.chain(target)
            if inner is None:
                return None
            sl = node.slice
            if isinstance(sl, ast.List):
                return inner[0], inner[1] + [b.select(*_strs(sl))]
            if isinstance(sl, ast.Constant):
                return None  # a single column (a Series), not a table
            return inner[0], inner[1] + [b.where(self.mask(sl))]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            method, recv = node.func.attr, node.func.value
            if method == "agg" and isinstance(recv, ast.Call) and \
                    isinstance(recv.func, ast.Attribute) and recv.func.attr == "groupby":
                inner = self.chain(recv.func.value)
                if inner is None:
                    return None
                return inner[0], inner[1] + [self.group(recv, node)]
            inner = self.chain(recv)
            if inner is None:
                return None
            base, steps = inner
            if method == "merge" and node.args:
                return base, steps + [self.join(node, node.args[0])]
            if method == "assign":
                out = []
                for k in node.keywords:
                    v = k.value
                    if isinstance(v, ast.Lambda):
                        v = v.body
                    if k.arg is None:
                        raise Unsupported("assign(**...)")
                    out.append(b.derive(k.arg, self.mask(v)))
                return base, steps + out
            if method == "query" and node.args:
                q = _const(node.args[0], str)
                try:
                    tree = ast.parse(q.replace("\n", " "), mode="eval").body
                except SyntaxError as exc:
                    raise Unsupported("query") from exc
                return base, steps + [b.where(self.mask(tree, bare=True))]
            if method == "sort_values":
                by = node.args[0] if node.args else _kw(node, "by")
                cols = _strs(by)
                asc = _kw(node, "ascending")
                if asc is None:
                    flags = [True] * len(cols)
                elif isinstance(asc, (ast.List, ast.Tuple)):
                    flags = [_const(e, bool) for e in asc.elts]
                else:
                    flags = [_const(asc, bool)] * len(cols)
                return base, steps + [b.order(*[(c, not a) for c, a in zip(cols, flags)])]
            if method == "head":
                n = _const(node.args[0], int) if node.args else 5
                return base, steps + [b.limit(n)]
            if method == "drop_duplicates" and steps and steps[-1].type == "select":
                sel = steps.pop()
                return base, steps + [b.group(sel.field("columns"))]
            if method in ("reset_index", "copy") and not node.args:
                return base, steps
            raise Unsupported(f".{method}()", node.lineno)
        return None

    def join(self, call: ast.Call, other: ast.expr) -> Block:
        if not (isinstance(other, ast.Name) and other.id in self.table_vars):
            raise Unsupported("merge needs a table read with read_csv", call.lineno)
        on = _kw(call, "on")
        if on is None:
            raise Unsupported("merge needs on=", call.lineno)
        keys = _strs(on)
        if len(keys) != 1:
            raise Unsupported("merge on several columns", call.lineno)
        how = _kw(call, "how")
        how_s = _const(how, str) if how is not None else "inner"
        if how_s not in ("inner", "left"):
            raise Unsupported(f'how="{how_s}"', call.lineno)
        blk = b.join(self.table_vars[other.id][0], keys[0], how_s)
        blk.fields["_var"] = other.id
        return blk

    def group(self, gcall: ast.Call, acall: ast.Call) -> Block:
        by = gcall.args[0] if gcall.args else _kw(gcall, "by")
        keys = _strs(by)
        aggs = []
        if acall.args:
            raise Unsupported("agg needs named summaries like avg=(\"col\", \"mean\")")
        for k in acall.keywords:
            v = k.value
            if not (isinstance(v, ast.Tuple) and len(v.elts) == 2):
                raise Unsupported("agg needs named summaries like avg=(\"col\", \"mean\")")
            col, fn = _const(v.elts[0], str), _const(v.elts[1], str)
            if fn not in AGG:
                raise Unsupported(f'"{fn}" summary')
            aggs.append(b.agg(AGG[fn], None if fn == "size" else col, k.arg))
        return b.group(keys, *aggs)

    def whole_table(self, d: ast.Dict) -> tuple[str, list[Block]] | None:
        aggs, base = [], None
        for k, v in zip(d.keys, d.values):
            alias = _const(k, str)
            if not (isinstance(v, ast.List) and len(v.elts) == 1):
                return None
            e = v.elts[0]
            if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "len" \
                    and isinstance(e.args[0], ast.Name):
                base = e.args[0].id
                aggs.append(b.agg("count", None, alias))
            elif isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and \
                    e.func.attr in AGG and isinstance(e.func.value, ast.Subscript) and \
                    isinstance(e.func.value.value, ast.Name):
                base = e.func.value.value.id
                aggs.append(b.agg(AGG[e.func.attr], _const(e.func.value.slice, str), alias))
            else:
                return None
        if base is None or not self.is_frame(base):
            return None
        return base, [b.group([], *aggs)]

    # ---- expressions -----------------------------------------------------------------------

    def mask(self, e: ast.expr, bare: bool = False) -> Block:
        """A pandas column expression (or a .query() string when ``bare``)."""
        m = lambda x: self.mask(x, bare)  # noqa: E731
        if isinstance(e, ast.Subscript) and isinstance(e.value, ast.Name) and \
                self.is_frame(e.value.id):
            return b.col(_const(e.slice, str))
        if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and \
                self.is_frame(e.value.id):
            return b.col(e.attr)
        if bare and isinstance(e, ast.Name):
            return b.col(e.id)
        if isinstance(e, ast.Constant) or (isinstance(e, ast.UnaryOp) and
                                           isinstance(e.op, ast.USub)):
            return b.lit(_const(e))
        if isinstance(e, ast.Compare):
            return self._compare(e, m)
        if isinstance(e, ast.BinOp):
            if isinstance(e.op, ast.BitAnd):
                return b.and_(m(e.left), m(e.right))
            if isinstance(e.op, ast.BitOr):
                return b.or_(m(e.left), m(e.right))
            if type(e.op) in MATH:
                return b.math(MATH[type(e.op)], m(e.left), m(e.right))
        if isinstance(e, ast.BoolOp):
            return self._boolop(e, m)
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, (ast.Invert, ast.Not)):
            return b.not_(m(e.operand))
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute):
            meth, recv = e.func.attr, e.func.value
            if meth in ("isna", "isnull") and not e.args:
                return b.isempty(m(recv))
            if meth in ("notna", "notnull") and not e.args:
                return b.not_(b.isempty(m(recv)))
            if meth == "isin" and len(e.args) == 1 and isinstance(e.args[0], (ast.List, ast.Tuple)):
                return b.inlist(m(recv), [_const(x) for x in e.args[0].elts])
            if meth == "between" and len(e.args) == 2:
                col = m(recv)
                return b.and_(b.cmp(">=", col, m(e.args[0])),
                              b.cmp("<=", col.model_copy(deep=True), m(e.args[1])))
            if meth in ("contains", "startswith", "endswith") and \
                    isinstance(recv, ast.Attribute) and recv.attr == "str" and e.args:
                target = recv.value
                if isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute) and \
                        target.func.attr == "lower" and isinstance(target.func.value, ast.Attribute) \
                        and target.func.value.attr == "str":
                    target = target.func.value.value
                op = {"contains": "contains", "startswith": "starts", "endswith": "ends"}[meth]
                return b.text(op, m(target), _const(e.args[0], str))
        raise Unsupported("expression", getattr(e, "lineno", None))

    def iexpr(self, e: ast.expr) -> Block:
        """A plain Python value (inside loops, ifs and prints)."""
        m = self.iexpr
        if isinstance(e, ast.Name):
            if e.id in ("True", "False", "None"):
                return b.lit({"True": True, "False": False, "None": None}[e.id])
            return b.var(e.id)
        if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and \
                not self.is_frame(e.value.id):
            return b.field(e.value.id, e.attr)
        if isinstance(e, ast.Constant) or (isinstance(e, ast.UnaryOp) and
                                           isinstance(e.op, ast.USub) and
                                           isinstance(e.operand, ast.Constant)):
            return b.lit(_const(e))
        if isinstance(e, ast.Compare):
            if len(e.ops) == 1 and isinstance(e.ops[0], ast.In):
                right = e.comparators[0]
                if isinstance(right, (ast.List, ast.Tuple)):
                    return b.inlist(m(e.left), [_const(x) for x in right.elts])
                return b.text("contains", m(_unwrap_str_lower(right)), _const(e.left, str))
            return self._compare(e, m)
        if isinstance(e, ast.BoolOp):
            return self._boolop(e, m)
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
            return b.not_(m(e.operand))
        if isinstance(e, ast.BinOp) and type(e.op) in MATH:
            return b.math(MATH[type(e.op)], m(e.left), m(e.right))
        if isinstance(e, ast.Call):
            f = e.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and \
                    f.value.id == "pd" and f.attr in ("isna", "isnull") and len(e.args) == 1:
                return b.isempty(m(e.args[0]))
            if isinstance(f, ast.Attribute) and f.attr in ("startswith", "endswith") and e.args:
                op = "starts" if f.attr == "startswith" else "ends"
                return b.text(op, m(_unwrap_str_lower(f.value)), _const(e.args[0], str))
        raise Unsupported("expression", getattr(e, "lineno", None))

    def _compare(self, e: ast.Compare, m) -> Block:
        parts, left = [], e.left
        for op, right in zip(e.ops, e.comparators):
            if type(op) not in CMP:
                raise Unsupported("comparison", e.lineno)
            parts.append(b.cmp(CMP[type(op)], m(left), m(right)))
            left = right
        out = parts[0]
        for p in parts[1:]:
            out = b.and_(out, p)
        return out

    def _boolop(self, e: ast.BoolOp, m) -> Block:
        fn = b.and_ if isinstance(e.op, ast.And) else b.or_
        out = m(e.values[0])
        for v in e.values[1:]:
            out = fn(out, m(v))
        return out


def _unwrap_str_lower(e: ast.expr) -> ast.expr:
    """str(x).lower() / x.lower() / str(x) → x"""
    if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr == "lower":
        e = e.func.value
    if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "str" and e.args:
        e = e.args[0]
    return e
