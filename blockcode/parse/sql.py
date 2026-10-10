"""SQL → blocks with sqlglot. Each SELECT becomes one From stack."""

from __future__ import annotations

import re
import sqlite3

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from blockcode import build as b
from blockcode.diagnostics import Diagnostic, error
from blockcode.ir import Block, Program, TableInfo
from blockcode.parse import ParseResult, Spans, Unsupported, default_names

AGGS = {exp.Avg: "avg", exp.Sum: "sum", exp.Min: "min", exp.Max: "max", exp.Count: "count"}
CMPS = {exp.EQ: "=", exp.NEQ: "!=", exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<="}
MATHS = {exp.Add: "+", exp.Sub: "-", exp.Mul: "*", exp.Div: "/", exp.Mod: "%"}
CLAUSE = re.compile(r"^\s*(select|from|(?:(?:left|inner|natural|cross)\s+(?:outer\s+)?)?join|"
                    r"where|and|or|group\s+by|having|order\s+by|limit)\b", re.I)


def split_statements(code: str) -> list[tuple[str, int, int]]:
    """(text, first line, last line) for each statement; blank lines between are skipped."""
    out, buf, start = [], [], None
    lines = code.split("\n")
    for i, line in enumerate(lines, start=1):
        if start is None:
            if not line.strip() or line.strip().startswith("--"):
                continue
            start = i
        buf.append(line)
        text = "\n".join(buf)
        if sqlite3.complete_statement(text):
            out.append((text, start, i))
            buf, start = [], None
    if buf and "\n".join(buf).strip():
        out.append(("\n".join(buf), start or 1, len(lines)))
    return out


def parse_sql(code: str, tables: dict[str, TableInfo], previous: Program | None) -> ParseResult:
    spans = Spans()
    blocks: list[Block] = []
    names = default_names(previous)
    diags: list[Diagnostic] = []
    for i, (text, first, _last) in enumerate(split_statements(code)):
        try:
            tree = sqlglot.parse_one(text, read="sqlite")
        except (ParseError, TokenError) as exc:
            line = first
            errs = getattr(exc, "errors", None) or []
            if errs and errs[0].get("line"):
                line = first + errs[0]["line"] - 1
            msg = errs[0].get("description") if errs else str(exc).splitlines()[0]
            return ParseResult(ok=False, lang="sql", diagnostics=[
                error(f"The SQL has a typo: {msg}", line=line, target="sql")])
        if tree is None:
            continue
        name = names[i] if i < len(names) else ("out" if i == 0 else f"out{i + 1}")
        try:
            blocks.append(_Select(tree, text, first, name, spans).build())
        except Unsupported as exc:
            diags.append(error(f"Not a block yet: {exc}", line=exc.line or first,
                               target="sql"))
    if diags:
        return ParseResult(ok=False, lang="sql", diagnostics=diags)
    return ParseResult(ok=True, lang="sql", program=Program(blocks=blocks), spans=spans.map)


def _ident(node) -> str:
    if isinstance(node, exp.Identifier):
        return node.this
    if isinstance(node, exp.Column):
        return node.name
    if isinstance(node, str):
        return node
    return node.name


class _Select:
    def __init__(self, tree: exp.Expression, text: str, first: int, name: str,
                 spans: Spans) -> None:
        self.tree, self.first, self.name, self.spans = tree, first, name, spans
        self.lines = text.split("\n")
        self.clauses = self._clause_lines()
        self.derived: dict[str, exp.Expression] = {}
        self.pending_derives: list[Block] = []

    # ---- line bookkeeping ------------------------------------------------------------------

    def _clause_lines(self) -> list[tuple[str, int, str | None]]:
        """(owning clause, absolute line, keyword the line starts with) for every line."""
        out, cur = [], "select"
        for i, line in enumerate(self.lines):
            m = CLAUSE.match(line)
            head = None
            if m:
                head = re.sub(r"\s+", " ", m.group(1).lower())
                if head.endswith("join"):
                    head = "join"
                if head not in ("and", "or"):
                    cur = head
            out.append((cur, self.first + i, head))
        return out

    def lines_of(self, clause: str) -> list[int]:
        return [n for c, n, _ in self.clauses if c == clause]

    def starts_of(self, clause: str) -> list[int]:
        return [n for _, n, h in self.clauses if h == clause]

    def start(self, clause: str) -> int:
        """The line a clause starts on (the query's first line when it shares a line)."""
        return (self.starts_of(clause) or [self.first])[0]

    # ---- building --------------------------------------------------------------------------

    def build(self) -> Block:
        t = self.tree
        if not isinstance(t, exp.Select):
            raise Unsupported("only SELECT queries can become blocks.", self.first)
        for key in ("with", "offset", "windows", "qualify", "distinct_on"):
            if t.args.get(key):
                raise Unsupported(f"{key.upper()} isn't a block yet.", self.first)
        src = t.args.get("from_") or t.args.get("from")
        if src is None or not isinstance(src.this, exp.Table):
            raise Unsupported("FROM needs a table name (subqueries aren't blocks yet).",
                              self.first)
        frm = b.from_(src.this.name, name=self.name)
        self.spans.add(frm, *self.starts_of("from"))
        steps: list[Block] = []

        for k, j in enumerate(t.args.get("joins") or []):
            steps.append(self._join(j, k))

        # SELECT list: collect columns, aggregates and named expressions
        star, plain, aggs, derived_items, order_names = False, [], [], [], []
        for item in t.expressions:  # named sums first, so summaries can refer to them
            if isinstance(item, exp.Alias) and type(item.this) not in AGGS and \
                    not (isinstance(item.this, exp.Column) and item.this.name == item.alias):
                self.derived[item.alias] = item.this
        for item in t.expressions:
            if isinstance(item, exp.Star):
                star = True
                continue
            alias = None
            node = item
            if isinstance(item, exp.Alias):
                alias, node = item.alias, item.this
            if type(node) in AGGS:
                aggs.append(self._agg(node, alias))
                order_names.append(aggs[-1]["as"])
            elif isinstance(node, exp.Column) and not alias:
                plain.append(node.name)
                order_names.append(node.name)
            elif isinstance(node, exp.Column) and alias == node.name:
                plain.append(node.name)
                order_names.append(node.name)
            else:
                if not alias:
                    raise Unsupported("give each worked-out column a name with AS.",
                                      self._line_with(item.sql(dialect="sqlite")))
                derived_items.append((alias, node))
                order_names.append(alias)

        sel_lines = self.lines_of("select")
        for alias, node in derived_items:
            others = {k: v for k, v in self.derived.items() if k != alias}
            saved, self.derived = self.derived, others
            d = b.derive(alias, self._expr(node))
            self.derived = saved
            steps.append(self.spans.add(d, self._line_with(f"AS {alias}", sel_lines)))

        where = t.args.get("where")
        if where is not None:
            steps += self._wheres(where.this)

        group = t.args.get("group")
        distinct = bool(t.args.get("distinct"))
        grouping = bool(group) or bool(aggs) or distinct
        if grouping:
            if star:
                raise Unsupported("SELECT * can't be grouped; list the columns instead.",
                                  self.first)
            keys = [self._key(k) for k in (group.expressions if group else [])]
            at = len(t.args.get("joins") or [])
            steps[at:at] = self.pending_derives
            if distinct and not keys:
                keys = list(order_names)
            g = b.group(keys, *aggs)
            canonical = keys + [a["as"] for a in aggs]
            for n in order_names:
                if n not in canonical:
                    raise Unsupported(f'"{n}" must be in GROUP BY or be a summary.',
                                      self._line_with(n, sel_lines))
            self.spans.add(g, *sel_lines, *self.starts_of("group by"))
            steps.append(g)
            having = t.args.get("having")
            if having is not None:
                hv = b.having(self._expr(having.this, aggs=aggs))
                steps.append(self.spans.add(hv, *self.lines_of("having")))
            if order_names != canonical:
                s = b.select(*order_names)
                steps.append(self.spans.add(s, *sel_lines))
        else:
            if t.args.get("having") is not None:
                raise Unsupported("HAVING needs a GROUP BY.", self.start("having"))
            if not star:
                s = b.select(*order_names)
                steps.append(self.spans.add(s, *sel_lines))
            elif plain:
                raise Unsupported("mixing * with named columns isn't a block yet.", self.first)
            else:
                self.spans.add(frm, *[ln for ln in sel_lines if "*" in self._text(ln)])

        order = t.args.get("order")
        if order is not None:
            keys = []
            for o in order.expressions:
                node = o.this if isinstance(o, exp.Ordered) else o
                if not isinstance(node, exp.Column):
                    raise Unsupported("ORDER BY needs column names.", self.start("order by"))
                keys.append((node.name, bool(o.args.get("desc"))))
            steps.append(self.spans.add(b.order(*keys), *self.lines_of("order by")))

        lim = t.args.get("limit")
        if lim is not None:
            n = lim.expression if lim.expression is not None else lim.this
            if not (isinstance(n, exp.Literal) and not n.is_string and n.this.isdigit()):
                raise Unsupported("LIMIT needs a whole number.", self.start("limit"))
            steps.append(self.spans.add(b.limit(int(n.this)), *self.lines_of("limit")))

        frm.stacks["steps"] = steps
        return frm

    def _text(self, line: int) -> str:
        return self.lines[line - self.first]

    def _line_with(self, needle: str, within: list[int] | None = None) -> int:
        pool = within or [self.first + i for i in range(len(self.lines))]
        for n in pool:
            if needle.lower() in self._text(n).lower():
                return n
        return pool[0] if pool else self.first

    def _join(self, j: exp.Join, k: int) -> Block:
        starts = self.starts_of("join")
        line = starts[min(k, len(starts) - 1)] if starts else self.first
        side = (j.args.get("side") or "").upper()
        kind = (j.args.get("kind") or "").upper()
        if kind in ("CROSS", "NATURAL") or side in ("RIGHT", "FULL"):
            raise Unsupported(f"{side or kind} JOIN isn't a block yet.", line)
        if not isinstance(j.this, exp.Table):
            raise Unsupported("JOIN needs a table name.", line)
        using = j.args.get("using")
        on = j.args.get("on")
        if using:
            if len(using) != 1:
                raise Unsupported("JOIN on more than one column isn't a block yet.", line)
            key = _ident(using[0])
        elif isinstance(on, exp.EQ) and isinstance(on.this, exp.Column) and \
                isinstance(on.expression, exp.Column) and on.this.name == on.expression.name:
            key = on.this.name
        else:
            raise Unsupported("JOIN needs USING (column) or ON a.col = b.col with the same "
                              "column name.", line)
        how = "left" if side == "LEFT" else "inner"
        return self.spans.add(b.join(j.this.name, key, how), line)

    def _wheres(self, cond: exp.Expression) -> list[Block]:
        """One Where block per line that starts with WHERE or AND, when that split doesn't
        change the meaning; otherwise one Where block for the whole condition."""
        def flatten(e, out):
            if isinstance(e, exp.And):
                flatten(e.this, out)
                flatten(e.expression, out)
            else:
                out.append(e)
            return out

        heads = [n for c, n, h in self.clauses if c == "where" and h in ("where", "and")]
        where_lines = self.lines_of("where")
        if len(heads) > 1:
            chunks = []
            for i, start in enumerate(heads):
                stop = heads[i + 1] if i + 1 < len(heads) else where_lines[-1] + 1
                text = " ".join(self._text(n) for n in range(start, stop))
                text = re.sub(r"^\s*(where|and)\b", "", text, flags=re.I).rstrip().rstrip(";")
                try:
                    chunks.append((sqlglot.parse_one(text, read="sqlite"), start, stop - 1))
                except (ParseError, TokenError):
                    chunks = []
                    break
            together = [p for c, _, _ in chunks for p in flatten(c, [])]
            if chunks and together == flatten(cond, []):
                return [self.spans.add(b.where(self._expr(c)), *range(a, z + 1))
                        for c, a, z in chunks]
        return [self.spans.add(b.where(self._expr(cond)), *where_lines)]

    def _key(self, k: exp.Expression) -> str:
        if isinstance(k, exp.Paren):
            k = k.this
        if isinstance(k, exp.Column):
            return k.name
        for name, d in self.derived.items():
            if d == k:
                return name
        # GROUP BY grade / 10: show the sum as a new column and group by that
        name = f"group_key{len(self.pending_derives) + 1}"
        self.derived[name] = k
        line = self.start("group by")
        self.pending_derives.append(self.spans.add(b.derive(name, self._expr(k)), line))
        return name

    def _agg(self, node: exp.Expression, alias: str | None) -> dict:
        func = AGGS[type(node)]
        arg = node.this
        if isinstance(arg, exp.Distinct):
            raise Unsupported("COUNT(DISTINCT ...) isn't a block yet.", self._line_with("distinct"))
        if isinstance(arg, exp.Star) or arg is None:
            column = None
        elif isinstance(arg, exp.Column):
            column = arg.name
        else:
            column = None
            for name, d in self.derived.items():
                if d == arg:
                    column = name
            if column is None:
                # AVG(grade / 2): show the sum as a new column, then summarise that column
                column = f"{alias or func}_input"
                d = b.derive(column, self._expr(arg))
                self.derived[column] = arg
                self.pending_derives.append(
                    self.spans.add(d, self._line_with(node.sql(dialect="sqlite")[:10])))
        if func != "count" and column is None:
            raise Unsupported(f"{func.upper()} needs a column.", self.first)
        return b.agg(func, column, alias or ("n" if func == "count" and not column
                                             else f"{func}_{column}"))

    def _expr(self, e: exp.Expression, aggs: list[dict] | None = None) -> Block:
        t = type(e)
        if t is exp.Paren:
            return self._expr(e.this, aggs)
        for name, d in self.derived.items():
            # SQL repeats a new column's sum wherever it is used; show it as the column again
            if e == d:
                return b.col(name)
        if t in CMPS:
            return b.cmp(CMPS[t], self._expr(e.this, aggs), self._expr(e.expression, aggs))
        if t is exp.And:
            return b.and_(self._expr(e.this, aggs), self._expr(e.expression, aggs))
        if t is exp.Or:
            return b.or_(self._expr(e.this, aggs), self._expr(e.expression, aggs))
        if t is exp.Not:
            inner = e.this.this if isinstance(e.this, exp.Paren) else e.this
            return b.not_(self._expr(inner, aggs))
        if t is exp.Is:
            if isinstance(e.expression, exp.Null):
                return b.isempty(self._expr(e.this, aggs))
            raise Unsupported("IS only works with NULL here.", self._line_with(" is "))
        if t is exp.In:
            vals = []
            for v in e.expressions:
                lit = self._expr(v)
                if lit.type != "lit":
                    raise Unsupported("IN needs a list of values.", self._line_with(" in "))
                vals.append(lit.field("value"))
            if e.args.get("query"):
                raise Unsupported("IN (SELECT ...) isn't a block yet.", self._line_with(" in "))
            return b.inlist(self._expr(e.this, aggs), vals)
        if t in (exp.Like, exp.ILike):
            pat = e.expression
            if not (isinstance(pat, exp.Literal) and pat.is_string):
                raise Unsupported("LIKE needs a text pattern.", self._line_with("like"))
            p = pat.this
            core = p.strip("%")
            if "%" in core or "_" in core:
                raise Unsupported("LIKE patterns with % or _ in the middle aren't blocks yet.",
                                  self._line_with("like"))
            if p.startswith("%") and p.endswith("%") and len(p) >= 2:
                op = "contains"
            elif p.endswith("%"):
                op = "starts"
            elif p.startswith("%"):
                op = "ends"
            else:
                return b.cmp("=", self._expr(e.this, aggs), b.lit(p))
            return b.text(op, self._expr(e.this, aggs), core)
        if t in MATHS:
            right = self._expr(e.expression, aggs)
            if t is exp.Div and right.type == "lit" and isinstance(right.field("value"), float) \
                    and right.field("value").is_integer():
                right.fields["value"] = int(right.field("value"))
            return b.math(MATHS[t], self._expr(e.this, aggs), right)
        if t is exp.Cast:
            return self._expr(e.this, aggs)
        if t is exp.Column:
            name = e.name
            return b.col(name)
        if t is exp.Literal:
            if e.is_string:
                return b.lit(e.this)
            v = float(e.this)
            return b.lit(int(v) if re.fullmatch(r"-?\d+", e.this) else v)
        if t is exp.Neg and isinstance(e.this, exp.Literal) and not e.this.is_string:
            v = self._expr(e.this)
            return b.lit(-v.field("value"))
        if t is exp.Boolean:
            return b.lit(bool(e.this))
        if t is exp.Null:
            return b.lit(None)
        if t in AGGS and aggs is not None:
            want = self._agg(e, None)
            for a in aggs:
                if a["func"] == want["func"] and a["column"] == want["column"]:
                    return b.col(a["as"])
            raise Unsupported("put this summary in the SELECT list with a name to use it here.",
                              self._line_with(e.sql(dialect="sqlite")))
        raise Unsupported(f"{e.sql(dialect='sqlite')} isn't a block yet.",
                          self._line_with(e.sql(dialect="sqlite")[:12]))
