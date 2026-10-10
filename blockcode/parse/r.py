"""R (dplyr / Quarto) → blocks with a small tokenizer and Pratt parser.

Covers the R that learners write for data work: ``<-``, ``|>`` and ``%>%`` pipes, dplyr verbs,
``for``/``if``/``while``, ``print``/``paste``/``cat`` and ggplot. Anything else becomes a raw
Code block. In a Quarto document only the ```{r} chunks are read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from blockcode import build as b
from blockcode.diagnostics import Diagnostic, error
from blockcode.ir import Block, Program, TableInfo
from blockcode.parse import ParseResult, Spans, Unsupported, table_for_path

# ---- tokenizer ---------------------------------------------------------------------------------

TOKEN = re.compile(r"""
    (?P<nl>\n)
  | (?P<ws>[ \t\r]+)
  | (?P<comment>\#[^\n]*)
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?L?)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<bt>`[^`]*`)
  | (?P<name>(?:[A-Za-z]|\.(?!\d))[A-Za-z0-9._]*)
  | (?P<op><<-|->>|<-|->|\|>|%[^%\n]*%|==|!=|<=|>=|&&|\|\||\[\[|[-+*/^<>!&|~?:=$@,;(){}\[\]])
""", re.X)


@dataclass
class Tok:
    kind: str  # nl, num, str, name, qname (backticked), op, eof
    value: str
    line: int


class RSyntaxError(Exception):
    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.line = line


def tokenize(code: str) -> list[Tok]:
    out, pos, line = [], 0, 1
    while pos < len(code):
        m = TOKEN.match(code, pos)
        if not m:
            raise RSyntaxError(f"unexpected character {code[pos]!r}", line)
        kind = m.lastgroup
        text = m.group()
        if kind == "nl":
            out.append(Tok("nl", "\n", line))
            line += 1
        elif kind in ("ws", "comment"):
            pass
        elif kind == "bt":
            out.append(Tok("qname", text[1:-1], line))  # `for` is a name, never a keyword
        elif kind == "str":
            body = text[1:-1]
            body = re.sub(r"\\(.)", lambda mm: {"n": "\n", "t": "\t"}.get(mm.group(1),
                                                                          mm.group(1)), body)
            out.append(Tok("str", body, line))
        else:
            out.append(Tok(kind, text, line))
        pos = m.end()
    out.append(Tok("eof", "", line))
    return out


# ---- AST -----------------------------------------------------------------------------------------

@dataclass
class N:
    kind: str  # num str name const call binop unary index dollar block if for while paren
    value: object = None
    kids: list = field(default_factory=list)
    args: list = field(default_factory=list)  # [(name | None, N)] for calls / index
    line: int = 0
    end: int = 0


BINARY = {  # op: (left bp, right bp)
    "=": (2, 1), "<-": (4, 3), "<<-": (4, 3), "->": (5, 6), "->>": (5, 6), "~": (7, 8),
    "||": (9, 10), "|": (9, 10), "&&": (11, 12), "&": (11, 12),
    "==": (15, 16), "!=": (15, 16), "<": (15, 16), ">": (15, 16), "<=": (15, 16), ">=": (15, 16),
    "+": (17, 18), "-": (17, 18), "*": (19, 20), "/": (19, 20),
    "|>": (21, 22), ":": (23, 24), "^": (28, 27),
}
NOT_BP, UNARY_BP, POSTFIX_BP = 13, 25, 30


class _Parser:
    def __init__(self, toks: list[Tok]) -> None:
        self.toks, self.i, self.depth = toks, 0, 0

    @property
    def tok(self) -> Tok:
        return self.toks[self.i]

    def next(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def last_line(self) -> int:
        return self.toks[max(self.i - 1, 0)].line

    def skip_nl(self) -> None:
        while self.tok.kind == "nl" or self.tok.value == ";":
            self.i += 1

    def expect(self, value: str) -> Tok:
        if self.depth:
            self.skip_nl()
        if self.tok.value != value:
            raise RSyntaxError(f"expected {value!r}", self.tok.line)
        return self.next()

    def program(self) -> list[N]:
        stmts = []
        self.skip_nl()
        while self.tok.kind != "eof":
            stmts.append(self.expr(0))
            if self.tok.kind not in ("nl", "eof") and self.tok.value != ";":
                raise RSyntaxError(f"unexpected {self.tok.value!r}", self.tok.line)
            self.skip_nl()
        return stmts

    def expr(self, min_bp: int) -> N:
        if self.depth:
            self.skip_nl()
        t = self.next()
        line = t.line
        if t.kind == "num":
            v = t.value.rstrip("L")
            node = N("num", int(v) if re.fullmatch(r"\d+", v) else float(v), line=line)
        elif t.kind == "str":
            node = N("str", t.value, line=line)
        elif t.kind == "qname":
            node = N("name", t.value, line=line)
        elif t.kind == "name":
            if t.value in ("TRUE", "FALSE", "T", "F"):
                node = N("const", t.value in ("TRUE", "T"), line=line)
            elif t.value in ("NA", "NULL", "NA_real_", "NA_character_", "NA_integer_"):
                node = N("const", None, line=line)
            elif t.value == "if":
                node = self.if_(line)
            elif t.value == "for":
                node = self.for_(line)
            elif t.value == "while":
                self.expect("(")
                self.depth += 1
                cond = self.expr(0)
                self.expect(")")
                self.depth -= 1
                node = N("while", kids=[cond, self.body()], line=line)
            elif t.value == "function":
                self.expect("(")
                depth = 1
                while depth:
                    tk = self.next()
                    if tk.kind == "eof":
                        raise RSyntaxError("missing )", line)
                    depth += {"(": 1, ")": -1}.get(tk.value, 0)
                node = N("function", kids=[self.body()], line=line)
            elif t.value == "repeat":
                node = N("repeat", kids=[self.body()], line=line)
            else:
                node = N("name", t.value, line=line)
        elif t.value == "(":
            self.depth += 1
            inner = self.expr(0)
            self.expect(")")
            self.depth -= 1
            node = N("paren", kids=[inner], line=line)
        elif t.value == "{":
            node = self.block(line)
        elif t.value in ("-", "+"):
            node = N("unary", t.value, kids=[self.expr(UNARY_BP)], line=line)
        elif t.value == "!":
            node = N("unary", "!", kids=[self.expr(NOT_BP)], line=line)
        else:
            raise RSyntaxError(f"unexpected {t.value or 'end of code'!r}", line)

        while True:
            op = self.tok
            if op.kind == "nl" and self.depth:
                save = self.i
                self.skip_nl()
                if self.tok.kind != "op" or self.tok.value in ("(", "[", "[[", "{", "!"):
                    self.i = save
                    break
                op = self.tok
            if op.kind == "op" and op.value in ("(", "[", "[[", "$", "@") and \
                    POSTFIX_BP > min_bp:
                self.next()
                if op.value == "(":
                    node = N("call", kids=[node], args=self.args(")"), line=line)
                elif op.value in ("[", "[["):
                    close = "]" if op.value == "[" else "]]"
                    node = N("index", kids=[node], args=self.args(close), line=line)
                else:
                    nm = self.next()
                    node = N("dollar", nm.value, kids=[node], line=line)
                continue
            if op.kind == "op" and (op.value in BINARY or op.value.startswith("%")):
                lbp, rbp = BINARY.get(op.value, (21, 22))
                if lbp <= min_bp:
                    break
                self.next()
                self.skip_nl()
                rhs = self.expr(rbp)
                node = N("binop", op.value, kids=[node, rhs], line=line)
                continue
            break
        node.end = self.last_line()
        return node

    def args(self, close: str) -> list[tuple[str | None, N | None]]:
        self.depth += 1
        out: list[tuple[str | None, N | None]] = []
        self.skip_nl()
        if close == "]]":
            pass
        while True:
            self.skip_nl()
            if self.tok.value == close or (close == "]]" and self.tok.value == "]"):
                break
            if self.tok.value == ",":
                out.append((None, None))  # empty arg, e.g. out[i, ]
                self.next()
                continue
            name = None
            if self.tok.kind in ("name", "qname", "str") and self.toks[self.i + 1].value == "=":
                name = self.next().value
                self.next()
            out.append((name, self.expr(0)))
            self.skip_nl()
            if self.tok.value == ",":
                self.next()
                self.skip_nl()
                if self.tok.value == close:
                    out.append((None, None))
                continue
            break
        self.skip_nl()
        if close == "]]":
            self.expect("]")
            self.expect("]")
        else:
            self.expect(close)
        self.depth -= 1
        return out

    def block(self, line: int) -> N:
        saved, self.depth = self.depth, 0
        stmts = []
        self.skip_nl()
        while self.tok.value != "}":
            if self.tok.kind == "eof":
                raise RSyntaxError("missing }", line)
            stmts.append(self.expr(0))
            self.skip_nl()
        self.next()
        self.depth = saved
        return N("block", kids=stmts, line=line, end=self.last_line())

    def body(self) -> N:
        self.skip_nl()
        return self.expr(0)

    def if_(self, line: int) -> N:
        self.expect("(")
        self.depth += 1
        cond = self.expr(0)
        self.expect(")")
        self.depth -= 1
        then = self.body()
        save = self.i
        self.skip_nl()
        if self.tok.value == "else":
            self.next()
            other = self.body()
            return N("if", kids=[cond, then, other], line=line)
        self.i = save
        return N("if", kids=[cond, then], line=line)

    def for_(self, line: int) -> N:
        self.expect("(")
        self.depth += 1
        var = self.next()
        if var.kind not in ("name", "qname"):
            raise RSyntaxError("for needs a variable name", var.line)
        if self.next().value != "in":
            raise RSyntaxError("expected 'in'", line)
        it = self.expr(0)
        self.expect(")")
        self.depth -= 1
        return N("for", var.value, kids=[it, self.body()], line=line)


def quarto_code(code: str) -> str:
    """Blank out everything outside ```{r} chunks (keeps line numbers)."""
    if not re.search(r"^```\{r", code, re.M):
        return code
    out, inside = [], False
    for line in code.split("\n"):
        if line.startswith("```{r"):
            inside = True
            out.append("")
        elif line.startswith("```"):
            inside = False
            out.append("")
        else:
            out.append(line if inside else "")
    return "\n".join(out)


# ---- R → blocks -------------------------------------------------------------------------------

CMP = {"==": "=", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
MATH = {"+": "+", "-": "-", "*": "*", "/": "/", "%%": "%"}
AGG = {"mean": "avg", "sum": "sum", "min": "min", "max": "max"}
SKIP_CALLS = {"library", "require", "suppressPackageStartupMessages", "options", "theme_set"}
GEOMS = {"geom_col": "bar", "geom_line": "line", "geom_point": "scatter",
         "geom_histogram": "hist", "geom_bar": "bar"}


def parse_r(code: str, tables: dict[str, TableInfo], previous: Program | None) -> ParseResult:
    src = quarto_code(code)
    try:
        stmts = _Parser(tokenize(src)).program()
    except RSyntaxError as exc:
        return ParseResult(ok=False, lang="r", diagnostics=[
            error(f"The R has a typo: {exc}", line=exc.line, target="r")])
    except Unsupported as exc:
        return ParseResult(ok=False, lang="r", diagnostics=[
            error(f"Not a block yet: {exc}", line=exc.line, target="r")])
    p = _RBlocks(src, tables)
    blocks = p.stmts(stmts)
    return ParseResult(ok=True, lang="r", program=Program(blocks=blocks), spans=p.spans.map,
                       diagnostics=p.diags)


def _call_name(n: N) -> str | None:
    if n.kind == "call" and n.kids[0].kind == "name":
        return n.kids[0].value
    return None


def _pos(n: N) -> list[N]:
    return [a for k, a in n.args if k is None and a is not None]


def _named(n: N, name: str) -> N | None:
    return next((a for k, a in n.args if k == name), None)


def _str(n: N | None) -> str:
    if n is not None and n.kind == "str":
        return n.value
    raise Unsupported("expected text here", n.line if n else None)


def _int(n: N | None) -> int:
    if n is not None and n.kind == "num" and float(n.value).is_integer():
        return int(n.value)
    raise Unsupported("expected a whole number here", n.line if n else None)


def _names(nodes: list[N]) -> list[str]:
    out = []
    for n in nodes:
        if n.kind == "name":
            out.append(n.value)
        elif n.kind == "str":
            out.append(n.value)
        else:
            raise Unsupported("expected column names here", n.line)
    return out


class _RBlocks:
    def __init__(self, code: str, tables: dict[str, TableInfo]) -> None:
        self.lines = code.split("\n")
        self.tables = tables
        self.spans = Spans()
        self.diags: list[Diagnostic] = []
        self.table_vars: dict[str, tuple[str, list[int]]] = {}
        self.pipes: dict[str, Block] = {}
        self._pending_group: tuple[list[str], list[int]] | None = None

    def rng(self, n: N) -> list[int]:
        return list(range(n.line, max(n.end, n.line) + 1))

    # ---- statements --------------------------------------------------------------------------

    def stmts(self, nodes: list[N]) -> list[Block]:
        out: list[Block] = []
        for n in nodes:
            try:
                made = self.stmt(n)
            except Unsupported:
                made = None
                self.raw(n, out)
            if made is not None:
                out.append(made)
        return out

    def raw(self, n: N, out: list[Block]) -> None:
        lines = self.rng(n)
        text = "\n".join(self.lines[i - 1] for i in lines)
        prev = out[-1] if out else None
        if prev is not None and prev.type == "raw" and \
                max(self.spans.map.get(prev.id, [0])) == n.line - 1:
            prev.fields["code"] += "\n" + text
            self.spans.add(prev, *lines)
        else:
            out.append(self.spans.add(b.raw("r", text), *lines))
        self.diags.append(Diagnostic(severity="info", line=n.line, target="r",
                                     message="This line can't become a block yet, so it stays "
                                             "as code."))

    def body_of(self, n: N) -> list[Block]:
        return self.stmts(n.kids if n.kind == "block" else [n])

    def stmt(self, n: N) -> Block | None:
        lines = self.rng(n)
        name = _call_name(n)
        if name in SKIP_CALLS:
            return None
        if n.kind == "binop" and n.value in ("<-", "=", "<<-"):
            target = n.kids[0]
            if target.kind != "name":
                raise Unsupported("assignment")
            return self.assign(target.value, n.kids[1], lines)
        if n.kind == "binop" and n.value == "->":
            if n.kids[1].kind != "name":
                raise Unsupported("assignment")
            return self.assign(n.kids[1].value, n.kids[0], lines)
        if n.kind == "name" and n.value in self.pipes:
            self.spans.add(self.pipes[n.value], *lines)
            return None
        if name in ("print", "cat", "message"):
            args = _pos(n)
            if name == "cat":
                args = [a for a in args if not (a.kind == "str" and a.value == "\n")]
            if name == "print" and len(args) == 1 and self.plot(args[0]) is not None:
                return self.spans.add(self.plot(args[0]), *lines)
            if len(args) == 1 and _call_name(args[0]) == "paste" and \
                    not _named(args[0], "sep"):
                args = _pos(args[0])
            return self.spans.add(b.print_(*[self.val(a) for a in args]), *lines)
        if n.kind == "for":
            return self.for_(n)
        if n.kind == "if":
            return self.if_(n)
        if n.kind == "while":
            blk = b.while_(self.val(n.kids[0]))
            self.spans.add(blk, n.line)
            blk.stacks["body"] = self.body_of(n.kids[1])
            self.spans.add(blk, n.kids[1].end)
            return blk
        plot = self.plot(n)
        if plot is not None:
            return self.spans.add(plot, *lines)
        raise Unsupported("statement", n.line)

    def if_(self, n: N) -> Block:
        blk = b.if_(self.val(n.kids[0]), [])
        self.spans.add(blk, n.line)
        blk.stacks["body"] = self.body_of(n.kids[1])
        self.spans.add(blk, n.kids[1].end)
        if len(n.kids) > 2:
            other = n.kids[2]
            blk.stacks["else"] = [self.if_(other)] if other.kind == "if" else self.body_of(other)
            self.spans.add(blk, other.end)
        return blk

    def for_(self, n: N) -> Block:
        var, it, body = n.value, n.kids[0], n.kids[1]
        stmts = body.kids if body.kind == "block" else [body]
        # for (i in seq_len(nrow(out))) { row <- out[i, ] ... }
        if _call_name(it) == "seq_len" and _pos(it) and _call_name(_pos(it)[0]) == "nrow" and \
                _pos(_pos(it)[0])[0].kind == "name" and stmts:
            data = _pos(_pos(it)[0])[0].value
            first = stmts[0]
            if first.kind == "binop" and first.value in ("<-", "=") and \
                    first.kids[0].kind == "name" and first.kids[1].kind == "index" and \
                    first.kids[1].kids[0].kind == "name" and first.kids[1].kids[0].value == data:
                blk = b.foreach(first.kids[0].value, b.var(data))
                self.spans.add(blk, n.line, first.line, body.end)
                blk.stacks["body"] = self.stmts(stmts[1:])
                return blk
        # for (i in seq_len(n) - 1) / for (i in 0:(n - 1))
        times = None
        if it.kind == "binop" and it.value == "-" and _call_name(it.kids[0]) == "seq_len" and \
                it.kids[1].kind == "num" and it.kids[1].value == 1:
            times = self.val(_pos(it.kids[0])[0])
        elif it.kind == "binop" and it.value == ":" and it.kids[0].kind == "num" and \
                it.kids[0].value == 0:
            upper = it.kids[1].kids[0] if it.kids[1].kind == "paren" else it.kids[1]
            if upper.kind == "num":
                times = b.lit(int(upper.value) + 1)
            elif upper.kind == "binop" and upper.value == "-" and upper.kids[1].kind == "num" \
                    and upper.kids[1].value == 1:
                times = self.val(upper.kids[0])
        if times is None:
            raise Unsupported("for loop", n.line)
        blk = b.repeat(var, times)
        self.spans.add(blk, n.line, body.end)
        blk.stacks["body"] = self.stmts(stmts)
        return blk

    def assign(self, target: str, value: N, lines: list[int]) -> Block | None:
        if _call_name(value) in ("read_csv", "read.csv", "read_csv2"):
            path = _str(_pos(value)[0] if _pos(value) else _named(value, "file"))
            self.table_vars[target] = (table_for_path(path, self.tables), lines)
            return None
        self._pending_group = None
        chain = self.chain(value)
        if self._pending_group is not None:
            self._pending_group = None
            raise Unsupported("group_by must be followed by summarise", value.line)
        if chain is not None:
            base, steps = chain
            if base not in self.pipes:
                table, tlines = self.table_vars[base]
                frm = b.from_(table, name=target)
                self.pipes[target] = frm
                self.spans.add(frm, *tlines, value.line)
                self.extend(frm, steps)
                return frm
            frm = self.pipes[base]
            self.extend(frm, steps)
            if target != base:
                frm.fields["name"] = target
                self.pipes[target] = frm
            if not steps:
                self.spans.add(frm, *lines)
            return None
        v = value.kids[0] if value.kind == "paren" else value
        if v.kind == "binop" and v.value == "+" and v.kids[0].kind == "name" and \
                v.kids[0].value == target:
            return self.spans.add(b.changevar(target, self.val(v.kids[1])), *lines)
        return self.spans.add(b.setvar(target, self.val(value)), *lines)

    def extend(self, frm: Block, steps: list[tuple[Block, list[int]]]) -> None:
        existing = frm.stacks.setdefault("steps", [])
        for s, lines in steps:
            self.spans.add(s, *lines)
            if s.type == "join":
                tv = s.fields.pop("_var", None)
                if tv in self.table_vars:
                    self.spans.add(s, *self.table_vars[tv][1])
            if s.type == "where" and any(x.type == "group" for x in existing):
                s = self.spans.add(b.having(s.inputs["cond"]), *lines)
                old = next((x for x in existing if x.type == "having"), None)
                if old is not None:
                    old.inputs["cond"] = b.and_(old.inputs["cond"], s.inputs["cond"])
                    self.spans.add(old, *lines)
                    continue
            existing.append(s)

    # ---- dplyr pipelines ---------------------------------------------------------------------

    def is_frame(self, name: str) -> bool:
        return name in self.pipes or name in self.table_vars

    def chain(self, n: N) -> tuple[str, list[tuple[Block, list[int]]]] | None:
        if n.kind == "paren":
            return self.chain(n.kids[0])
        if n.kind == "name":
            return (n.value, []) if self.is_frame(n.value) else None
        if n.kind == "binop" and n.value in ("|>", "%>%"):
            inner = self.chain(n.kids[0])
            if inner is None:
                return None
            rhs = n.kids[1]
            if rhs.kind == "name":
                rhs = N("call", kids=[rhs], args=[], line=rhs.line, end=rhs.end)
            if rhs.kind != "call":
                raise Unsupported("pipe", rhs.line)
            return inner[0], self.verb(rhs, inner[1])
        if n.kind == "call" and _pos(n):
            first = _pos(n)[0]
            inner = self.chain(first) if first.kind in ("name", "paren", "binop", "call") else None
            if inner is not None and _call_name(n) not in ("print", "nrow"):
                rest = N("call", kids=n.kids, line=n.line, end=n.end,
                         args=[a for a in n.args if a[1] is not first])
                return inner[0], self.verb(rest, inner[1])
        return None

    def verb(self, call: N, steps: list[tuple[Block, list[int]]]
             ) -> list[tuple[Block, list[int]]]:
        name = _call_name(call)
        lines = list(range(call.line, max(call.end, call.line) + 1))
        out = list(steps)
        add = lambda blk: out.append((blk, lines))  # noqa: E731
        pending = self._pending_group
        if pending is not None and name not in ("summarise", "summarize"):
            raise Unsupported("group_by must be followed by summarise", call.line)
        if name in ("inner_join", "left_join"):
            other = _pos(call)[0] if _pos(call) else _named(call, "y")
            if other is None or other.kind != "name" or other.value not in self.table_vars:
                raise Unsupported("join needs a table read with read_csv", call.line)
            by = _named(call, "by")
            if by is None and len(_pos(call)) > 1:
                by = _pos(call)[1]
            key = self._join_key(by, call.line)
            blk = b.join(self.table_vars[other.value][0], key,
                         "left" if name == "left_join" else "inner")
            blk.fields["_var"] = other.value
            add(blk)
        elif name == "filter":
            if any(k for k, _ in call.args):
                raise Unsupported("filter with named arguments", call.line)
            for cond in _pos(call):
                add(b.where(self.mask(cond)))
        elif name == "mutate":
            for k, v in call.args:
                if k is None or v is None:
                    raise Unsupported("mutate needs name = value", call.line)
                add(b.derive(k, self.mask(v)))
        elif name == "group_by":
            self._pending_group = (_names(_pos(call)), lines)
            return out
        elif name in ("summarise", "summarize"):
            keys, glines = pending if pending is not None else ([], [])
            self._pending_group = None
            aggs = []
            for k, v in call.args:
                if k == ".groups":
                    continue
                if k is None or v is None:
                    raise Unsupported("summarise needs name = summary", call.line)
                aggs.append(self._agg(k, v))
            out.append((b.group(keys, *aggs), glines + lines))
        elif name == "count":
            nm = _named(call, "name")
            add(b.group(_names(_pos(call)), b.agg("count", None, _str(nm) if nm else "n")))
        elif name == "distinct":
            add(b.group(_names(_pos(call))))
        elif name == "select":
            add(b.select(*_names(_pos(call))))
        elif name == "arrange":
            keys = []
            for a in _pos(call):
                if _call_name(a) == "desc":
                    keys.append((_names(_pos(a))[0], True))
                else:
                    keys.append((_names([a])[0], False))
            add(b.order(*keys))
        elif name in ("slice_head", "head"):
            n = _named(call, "n") or (_pos(call)[0] if _pos(call) else None)
            add(b.limit(_int(n) if n is not None else 6 if name == "head" else 1))
        elif name in ("ungroup", "as_tibble", "as.data.frame"):
            pass
        else:
            raise Unsupported(f"{name}()", call.line)
        return out

    def _join_key(self, by: N | None, line: int) -> str:
        if by is None:
            raise Unsupported("join needs by =", line)
        if by.kind == "str":
            return by.value
        if _call_name(by) in ("c", "join_by") and len(_pos(by)) == 1:
            a = _pos(by)[0]
            if a.kind in ("str", "name"):
                return a.value
        raise Unsupported("join on one column with the same name in both tables", line)

    def _agg(self, alias: str, v: N) -> dict:
        name = _call_name(v)
        if name == "n" and not v.args:
            return b.agg("count", None, alias)
        if name == "length" and len(_pos(v)) == 1:
            return b.agg("count", None, alias)
        if name == "sum" and len(_pos(v)) == 1:
            a = _pos(v)[0]
            if a.kind == "unary" and a.value == "!" and _call_name(a.kids[0]) == "is.na":
                return b.agg("count", _names(_pos(a.kids[0]))[0], alias)
        if name in AGG and _pos(v):
            return b.agg(AGG[name], _names([_pos(v)[0]])[0], alias)
        raise Unsupported(f"{name or 'this'} summary", v.line)

    # ---- plots -----------------------------------------------------------------------------

    def plot(self, n: N) -> Block | None:
        layers: list[N] = []
        cur = n
        while cur.kind == "binop" and cur.value == "+":
            layers.insert(0, cur.kids[1])
            cur = cur.kids[0]
        if _call_name(cur) != "ggplot":
            return None
        data = _pos(cur)[0] if _pos(cur) else _named(cur, "data")
        aes = _pos(cur)[1] if len(_pos(cur)) > 1 else _named(cur, "mapping")
        if data is None or data.kind != "name" or aes is None or _call_name(aes) != "aes":
            raise Unsupported("ggplot needs data and aes()", n.line)
        x = _named(aes, "x") or (_pos(aes)[0] if _pos(aes) else None)
        y = _named(aes, "y") or (_pos(aes)[1] if len(_pos(aes)) > 1 else None)
        geoms = [_call_name(layer) for layer in layers]
        if geoms == ["geom_line", "geom_point"] or geoms == ["geom_line"]:
            chart = "line"
        elif len(geoms) == 1 and geoms[0] in GEOMS:
            chart = GEOMS[geoms[0]]
        else:
            raise Unsupported("this kind of plot", n.line)
        blk = b.plot(chart, data.value, _names([x])[0] if x else None,
                     _names([y])[0] if y else None)
        if chart == "hist":
            bins = _named(layers[0], "bins")
            blk.fields["bins"] = _int(bins) if bins else 30
        return blk

    # ---- expressions -------------------------------------------------------------------------

    def mask(self, n: N) -> Block:
        return self._expr(n, columns=True)

    def val(self, n: N) -> Block:
        return self._expr(n, columns=False)

    def _expr(self, n: N, columns: bool) -> Block:
        e = lambda x: self._expr(x, columns)  # noqa: E731
        k = n.kind
        if k == "paren":
            return e(n.kids[0])
        if k == "num" or k == "str" or k == "const":
            return b.lit(n.value)
        if k == "name":
            return b.col(n.value) if columns else b.var(n.value)
        if k == "dollar" and n.kids[0].kind == "name":
            return b.field(n.kids[0].value, n.value)
        if k == "unary":
            if n.value == "!":
                return b.not_(e(n.kids[0]))
            if n.value == "-" and n.kids[0].kind == "num":
                return b.lit(-n.kids[0].value)
            if n.value == "+":
                return e(n.kids[0])
        if k == "binop":
            op = n.value
            if op in CMP:
                return b.cmp(CMP[op], e(n.kids[0]), e(n.kids[1]))
            if op in ("&", "&&"):
                return b.and_(e(n.kids[0]), e(n.kids[1]))
            if op in ("|", "||"):
                return b.or_(e(n.kids[0]), e(n.kids[1]))
            if op in MATH:
                return b.math(MATH[op], e(n.kids[0]), e(n.kids[1]))
            if op == "%in%" and _call_name(n.kids[1]) == "c":
                return b.inlist(e(n.kids[0]), [self._lit(a) for a in _pos(n.kids[1])])
        if k == "call":
            name = _call_name(n)
            args = _pos(n)
            if name == "is.na" and len(args) == 1:
                return b.isempty(e(args[0]))
            if name == "between" and len(args) == 3:
                col = e(args[0])
                return b.and_(b.cmp(">=", col, e(args[1])),
                              b.cmp("<=", e(args[0]), e(args[2])))
            if name in ("str_detect", "str_starts", "str_ends") and len(args) == 2:
                op = {"str_detect": "contains", "str_starts": "starts", "str_ends": "ends"}[name]
                return b.text(op, e(self._untolower(args[0])), self._pattern(args[1]))
            if name in ("startsWith", "endsWith") and len(args) == 2:
                op = "starts" if name == "startsWith" else "ends"
                return b.text(op, e(self._untolower(args[0])), _str(args[1]))
            if name == "grepl" and len(args) == 2:
                return b.text("contains", e(self._untolower(args[1])), self._pattern(args[0]))
            if name in ("str", "as.character") and len(args) == 1:
                return e(args[0])
        raise Unsupported("expression", n.line)

    def _lit(self, n: N):
        if n.kind in ("num", "str", "const"):
            return n.value
        if n.kind == "unary" and n.value == "-" and n.kids[0].kind == "num":
            return -n.kids[0].value
        raise Unsupported("expected a value", n.line)

    def _untolower(self, n: N) -> N:
        if _call_name(n) in ("tolower", "str_to_lower") and len(_pos(n)) == 1:
            return _pos(n)[0]
        return n

    def _pattern(self, n: N) -> str:
        if _call_name(n) == "fixed" and _pos(n):
            return _str(_pos(n)[0])
        if n.kind == "str" and not re.search(r"[.^$*+?()\[\]{}|\\]", n.value):
            return n.value
        raise Unsupported("regular expressions aren't blocks yet", n.line)
