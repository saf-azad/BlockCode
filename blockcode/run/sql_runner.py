"""Run generated SQL against the project's SQLite database (read-only)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from blockcode.codegen.emitter import Generated
from blockcode.errors import friendly
from blockcode.run import MAX_ROWS, RunError, RunResult, TableResult


def split_statements(gen: Generated) -> list[tuple[str, list[int]]]:
    """Split code into complete statements, keeping the line numbers of each."""
    out: list[tuple[str, list[int]]] = []
    buf: list[str] = []
    nums: list[int] = []
    for ln in gen.lines:
        if not buf and not ln.text.strip():
            continue
        buf.append(ln.text)
        nums.append(ln.n)
        text = "\n".join(buf)
        if sqlite3.complete_statement(text):
            out.append((text, nums))
            buf, nums = [], []
    if buf and "\n".join(buf).strip():
        out.append(("\n".join(buf), nums))
    return out


def _error_line(gen: Generated, nums: list[int], detail: str) -> int:
    """Best guess at the line an SQLite error points to: the first line naming the culprit."""
    m = re.search(r"(?:no such column|no such table|near): \"?([\w.]+)", detail)
    if m:
        word = m.group(1).split(".")[-1]
        for n in nums:
            text = gen.lines[n - 1].text
            if re.search(rf"\b{re.escape(word)}\b", text):
                return n
    return nums[0]


def run_sql(gen: Generated, db_path: Path, names: list[str] | None = None) -> RunResult:
    result = RunResult(target="sql", ok=True)
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        for i, (stmt, nums) in enumerate(split_statements(gen)):
            try:
                cur = conn.execute(stmt)
            except sqlite3.Error as exc:
                line = _error_line(gen, nums, str(exc))
                blocks = gen.blocks_at(line)
                result.ok = False
                result.error = RunError(kind=type(exc).__name__,
                                        message=friendly(type(exc).__name__, str(exc), "sql"),
                                        detail=str(exc), line=line,
                                        block_id=blocks[0] if blocks else None)
                return result
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                name = names[i] if names and i < len(names) else f"result {i + 1}"
                result.tables.append(TableResult(name=name, columns=cols,
                                                 rows=[list(r) for r in rows[:MAX_ROWS]],
                                                 total_rows=len(rows)))
    finally:
        conn.close()
    return result
