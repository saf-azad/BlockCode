"""Code → blocks. Each parser recognises the subset of SQL, pandas and dplyr that BlockCode
generates (plus the common ways people write the same thing by hand).

* A syntax error returns ``ok=False``: the editor keeps the blocks it has and shows the error.
* SQL that uses something we can't show as blocks also returns ``ok=False``, with a
  "not a block yet" message on the line.
* Python or R we can't show as blocks becomes a dashed "Code" (raw) block, so nothing typed
  is lost.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from blockcode.diagnostics import Diagnostic
from blockcode.ir import Block, Program, TableInfo


class ParseResult(BaseModel):
    ok: bool
    lang: str
    program: Program | None = None
    spans: dict[str, list[int]] = Field(default_factory=dict)  # block id → 1-based lines
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class Unsupported(Exception):
    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


class Spans:
    """Collects which lines each new block came from."""

    def __init__(self) -> None:
        self.map: dict[str, list[int]] = {}

    def add(self, block: Block, *lines: int | None) -> Block:
        cur = self.map.setdefault(block.id, [])
        for ln in lines:
            if ln is not None and ln not in cur:
                cur.append(ln)
        cur.sort()
        return block

    def add_range(self, block: Block, start: int, end: int) -> Block:
        return self.add(block, *range(start, end + 1))


def parse_code(code: str, lang: str, tables: list[TableInfo] | dict[str, TableInfo],
               previous: Program | None = None) -> ParseResult:
    if isinstance(tables, list):
        tables = {t.name: t for t in tables}
    if lang == "sql":
        from blockcode.parse.sql import parse_sql
        result = parse_sql(code, tables, previous)
    elif lang == "python":
        from blockcode.parse.python import parse_python
        result = parse_python(code, tables, previous)
    elif lang == "r":
        from blockcode.parse.r import parse_r
        result = parse_r(code, tables, previous)
    else:
        raise ValueError(f"Unknown language {lang!r}")
    if result.ok and result.program is not None and previous is not None:
        from blockcode.parse.match import keep_ids
        result.program, result.spans = keep_ids(result.program, previous, result.spans)
    return result


def table_for_path(path: str, tables: dict[str, TableInfo]) -> str:
    """Map "data/enrolments.csv" back to the table name."""
    from blockcode.data_io import table_name_for

    for t in tables.values():
        if t.file == path or t.file.endswith("/" + path.split("/")[-1]):
            return t.name
    return table_name_for(path)


def default_names(previous: Program | None) -> list[str]:
    names = [b.field("name") or "out" for b in (previous.blocks if previous else [])
             if b.type == "from"]
    return names
